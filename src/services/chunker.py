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
        self.min_chunk_size_tokens = config.min_chunk_size_tokens

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
        Chunk parsed content with structure awareness and smart section aggregation

        Args:
            parsed_content: Parsed markdown content with sections
            source_file: Path to source markdown file

        Returns:
            list[DocumentationChunk]: List of chunked documentation
        """
        chunks = []

        # If we have sections, aggregate small sections intelligently
        if parsed_content.sections:
            chunks = await self._chunk_with_section_aggregation(
                parsed_content.sections, source_file
            )
        else:
            # No sections, chunk the full text
            section_chunks = await self._chunk_section(parsed_content.text, None, source_file)
            chunks.extend(section_chunks)

        # Assign chunk positions
        for i, chunk in enumerate(chunks):
            chunk.chunk_position = i

        return chunks

    async def _chunk_with_section_aggregation(
        self, sections: list[tuple[str, str]], source_file: str
    ) -> list[DocumentationChunk]:
        """
        Intelligently aggregate small sections to create properly-sized chunks

        This method combines consecutive small sections until reaching the minimum
        chunk size, while respecting the maximum chunk size limit.

        Args:
            sections: List of (heading, content) tuples
            source_file: Path to source file

        Returns:
            list[DocumentationChunk]: Aggregated and chunked documentation
        """
        chunks = []
        aggregated_content = []
        aggregated_headings = []
        current_tokens = 0

        for i, (heading, content) in enumerate(sections):
            section_text = f"{content}"  # Content already includes heading
            section_tokens = self.count_tokens(section_text)
            is_last_section = (i == len(sections) - 1)

            # Check if adding this section would exceed max size
            if current_tokens > 0 and (current_tokens + section_tokens) > self.chunk_size_tokens:
                # Only create chunk if it meets minimum size
                # Exception: if this is second-to-last section and would create undersized
                # final chunk
                should_finalize = current_tokens >= self.min_chunk_size_tokens

                if not should_finalize and not is_last_section:
                    # Current accumulation is too small, but we'd exceed max by adding this section
                    # Check if we should continue anyway to avoid tiny chunks
                    peek_ahead_tokens = current_tokens + section_tokens
                    if peek_ahead_tokens <= self.chunk_size_tokens * 1.2:
                        # Within 20% over limit, include it to avoid undersized chunks
                        aggregated_content.append(section_text)
                        aggregated_headings.append(heading)
                        current_tokens += section_tokens
                        continue

                # Create chunk from accumulated content
                chunks.extend(
                    await self._create_aggregated_chunk(
                        aggregated_content, aggregated_headings, source_file
                    )
                )
                # Start new aggregation with current section
                aggregated_content = [section_text]
                aggregated_headings = [heading]
                current_tokens = section_tokens
            else:
                # Add to current aggregation
                aggregated_content.append(section_text)
                aggregated_headings.append(heading)
                current_tokens += section_tokens

        # Create final chunk from remaining content
        # Merge with last chunk if this would be too small
        if aggregated_content:
            if chunks and current_tokens < self.min_chunk_size_tokens:
                # Last chunk is too small, try to merge with previous chunk
                last_chunk = chunks[-1]
                combined_tokens = last_chunk.token_count + current_tokens

                if combined_tokens <= self.chunk_size_tokens * 1.2:
                    # Merge with previous chunk
                    chunks.pop()
                    combined_content = last_chunk.content + "\n\n" + "\n\n".join(aggregated_content)
                    chunks.append(
                        DocumentationChunk(
                            content=combined_content,
                            source_file=source_file,
                            section_heading=last_chunk.section_heading,
                            chunk_position=last_chunk.chunk_position,
                            token_count=combined_tokens,
                        )
                    )
                else:
                    # Can't merge, create separate small chunk
                    chunks.extend(
                        await self._create_aggregated_chunk(
                            aggregated_content, aggregated_headings, source_file
                        )
                    )
            else:
                # Normal case - create final chunk
                chunks.extend(
                    await self._create_aggregated_chunk(
                        aggregated_content, aggregated_headings, source_file
                    )
                )

        return chunks

    async def _create_aggregated_chunk(
        self, content_parts: list[str], headings: list[str], source_file: str
    ) -> list[DocumentationChunk]:
        """
        Create chunk(s) from aggregated content, splitting if necessary

        Args:
            content_parts: List of content strings to combine
            headings: List of section headings
            source_file: Path to source file

        Returns:
            list[DocumentationChunk]: One or more chunks
        """
        # Combine all content with double newlines for readability
        combined_content = "\n\n".join(content_parts)
        combined_tokens = self.count_tokens(combined_content)

        # Create section heading (combine multiple headings if aggregated)
        if len(headings) == 1:
            section_heading = headings[0]
        else:
            # Multiple sections aggregated - use first as main, indicate others
            section_heading = f"{headings[0]} (+ {len(headings)-1} more)"

        # If still within limits, return single chunk
        if combined_tokens <= self.chunk_size_tokens:
            return [
                DocumentationChunk(
                    content=combined_content,
                    source_file=source_file,
                    section_heading=section_heading,
                    chunk_position=0,
                    token_count=combined_tokens,
                )
            ]

        # Content too large, split it with overlap
        return await self._chunk_section(combined_content, section_heading, source_file)

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
