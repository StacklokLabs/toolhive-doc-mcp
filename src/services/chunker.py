"""Content chunking service with semantic awareness"""

import tiktoken

from src.config import config
from src.models.chunk import DocumentationChunk
from src.services.doc_parser import ParsedContent


class Chunker:
    """Chunk documentation content with token counting and structure awareness"""

    def __init__(self):
        self.chunk_size_tokens = config.chunk_size_tokens
        self.chunk_overlap_tokens = config.chunk_overlap_tokens

        # Initialize tiktoken encoder for OpenAI models
        try:
            self.encoder = tiktoken.encoding_for_model(config.embedding_model)
        except KeyError:
            # Fallback to cl100k_base (used by gpt-3.5 and gpt-4)
            self.encoder = tiktoken.get_encoding("cl100k_base")

    async def chunk(
        self, parsed_content: ParsedContent, source_file: str
    ) -> list[DocumentationChunk]:
        """
        Chunk parsed content with structure awareness

        Args:
            parsed_content: Parsed markdown content with sections
            source_file: Path to source markdown file

        Returns:
            list[DocumentationChunk]: List of chunked documentation
        """
        chunks = []

        # If we have sections, chunk by section
        if parsed_content.sections:
            for section_heading, section_content in parsed_content.sections:
                section_chunks = await self._chunk_section(
                    section_content, section_heading, source_file
                )
                chunks.extend(section_chunks)
        else:
            # No sections, chunk the full text
            section_chunks = await self._chunk_section(parsed_content.text, None, source_file)
            chunks.extend(section_chunks)

        # Assign chunk positions
        for i, chunk in enumerate(chunks):
            chunk.chunk_position = i

        return chunks

    async def _chunk_section(
        self, content: str, section_heading: str | None, source_file: str
    ) -> list[DocumentationChunk]:
        """
        Chunk a single section of content

        Respects token limits and creates overlapping chunks for context.
        """
        # Count tokens in content
        tokens = self.encoder.encode(content)
        total_tokens = len(tokens)

        # If section is small enough, return as single chunk
        if total_tokens <= self.chunk_size_tokens:
            return [
                DocumentationChunk(
                    content=content,
                    source_file=source_file,
                    section_heading=section_heading,
                    chunk_position=0,
                    token_count=total_tokens,
                )
            ]

        # Section too large, split into chunks with overlap
        chunks = []
        start_token = 0

        while start_token < total_tokens:
            # Determine end token for this chunk
            end_token = min(start_token + self.chunk_size_tokens, total_tokens)

            # Extract chunk tokens
            chunk_tokens = tokens[start_token:end_token]

            # Decode back to text
            chunk_text = self.encoder.decode(chunk_tokens)

            # Create chunk
            chunk = DocumentationChunk(
                content=chunk_text,
                source_file=source_file,
                section_heading=section_heading,
                chunk_position=len(chunks),
                token_count=len(chunk_tokens),
            )
            chunks.append(chunk)

            # Move start position with overlap
            if end_token == total_tokens:
                # Last chunk, done
                break
            else:
                # Move forward, leaving overlap
                start_token = end_token - self.chunk_overlap_tokens

        return chunks

    def count_tokens(self, text: str) -> int:
        """Count tokens in text using tiktoken"""
        return len(self.encoder.encode(text))

    async def chunk_by_paragraphs(
        self, content: str, section_heading: str | None, source_file: str
    ) -> list[DocumentationChunk]:
        """
        Alternative chunking strategy: split by paragraphs

        Respects paragraph boundaries instead of arbitrary token cutoffs.
        """
        paragraphs = content.split("\n\n")
        chunks = []
        current_chunk_text = []
        current_token_count = 0

        for para in paragraphs:
            para_tokens = self.count_tokens(para)

            # If adding this paragraph exceeds limit, finalize current chunk
            if current_token_count + para_tokens > self.chunk_size_tokens and current_chunk_text:
                chunk_text = "\n\n".join(current_chunk_text)
                chunks.append(
                    DocumentationChunk(
                        content=chunk_text,
                        source_file=source_file,
                        section_heading=section_heading,
                        chunk_position=len(chunks),
                        token_count=current_token_count,
                    )
                )
                # Start new chunk with overlap (include last paragraph)
                current_chunk_text = [current_chunk_text[-1]] if current_chunk_text else []
                current_token_count = (
                    self.count_tokens(current_chunk_text[0]) if current_chunk_text else 0
                )

            # Add paragraph to current chunk
            current_chunk_text.append(para)
            current_token_count += para_tokens

        # Add final chunk
        if current_chunk_text:
            chunk_text = "\n\n".join(current_chunk_text)
            chunks.append(
                DocumentationChunk(
                    content=chunk_text,
                    source_file=source_file,
                    section_heading=section_heading,
                    chunk_position=len(chunks),
                    token_count=current_token_count,
                )
            )

        return chunks
