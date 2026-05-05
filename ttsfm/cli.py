#!/usr/bin/env python3
"""
Command-line interface for TTSFM.

This module provides a command-line interface for the TTSFM package,
allowing users to generate speech from text using various options.
"""

import argparse
import os
import sys
from pathlib import Path

from .client import TTSClient
from .exceptions import APIException, NetworkException, TTSException
from .models import AudioFormat, TTSResponse, Voice


def create_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        prog="ttsfm",
        description="TTSFM - Text-to-Speech API Client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ttsfm "Hello, world!" --output hello.mp3
  ttsfm "Hello, world!" --voice nova --format wav --output hello.wav
  ttsfm "Hello, world!" --url https://www.openai.fm --output hello.mp3
  ttsfm --text-file input.txt --output speech.mp3
        """,
    )

    # Text input options (mutually exclusive)
    text_group = parser.add_mutually_exclusive_group(required=True)
    text_group.add_argument("text", nargs="?", help="Text to convert to speech")
    text_group.add_argument("--text-file", "-f", type=str, help="Read text from file")

    # Output options
    parser.add_argument("--output", "-o", type=str, required=True, help="Output file path")

    # TTS options
    parser.add_argument(
        "--voice",
        "-v",
        type=str,
        default="alloy",
        choices=[
            "alloy",
            "ash",
            "ballad",
            "coral",
            "echo",
            "fable",
            "nova",
            "onyx",
            "sage",
            "shimmer",
            "verse",
        ],
        help="Voice to use for speech generation (default: alloy)",
    )

    parser.add_argument(
        "--format",
        type=str,
        default="mp3",
        choices=["mp3", "opus", "aac", "flac", "wav", "pcm"],
        help="Audio format (default: mp3)",
    )

    parser.add_argument(
        "--speed", type=float, default=1.0, help="Speech speed (0.25 to 4.0, default: 1.0)"
    )

    # Client options
    parser.add_argument(
        "--url",
        "-u",
        type=str,
        default="https://www.openai.fm",
        help="TTS service URL (default: https://www.openai.fm)",
    )

    parser.add_argument("--api-key", "-k", type=str, help="API key for authentication")

    parser.add_argument(
        "--timeout", type=float, default=30.0, help="Request timeout in seconds (default: 30.0)"
    )

    parser.add_argument(
        "--retries", type=int, default=3, help="Maximum number of retries (default: 3)"
    )

    # Text length validation options
    parser.add_argument(
        "--max-length",
        type=int,
        default=1000,
        help="Maximum text length in characters (default: 1000)",
    )

    parser.add_argument(
        "--no-length-validation", action="store_true", help="Disable text length validation"
    )

    parser.add_argument(
        "--split-long-text", action="store_true", help="Automatically split long text into chunks"
    )

    parser.add_argument(
        "--auto-combine",
        action="store_true",
        help=(
            "Combine long-text chunks into a single audio file "
            "(requires pydub for non-WAV formats)"
        ),
    )

    # Other options
    parser.add_argument("--verbose", "-V", action="store_true", help="Enable verbose output")

    parser.add_argument("--version", action="version", version=f"%(prog)s {get_version()}")

    return parser


def get_version() -> str:
    """Get the package version."""
    try:
        from . import __version__

        return __version__
    except ImportError:
        return "unknown"


def read_text_file(file_path: str) -> str:
    """Read text from a file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading file '{file_path}': {e}", file=sys.stderr)
        sys.exit(1)


def validate_speed(speed: float) -> float:
    """Validate and return the speed parameter."""
    if not 0.25 <= speed <= 4.0:
        print("Error: Speed must be between 0.25 and 4.0", file=sys.stderr)
        sys.exit(1)
    return speed


def get_voice_enum(voice_str: str) -> Voice:
    """Convert voice string to Voice enum."""
    return Voice(voice_str.lower())


def get_format_enum(format_str: str) -> AudioFormat:
    """Convert format string to AudioFormat enum."""
    return AudioFormat(format_str.lower())


def handle_long_text(  # type: ignore[no-untyped-def]
    args,
    text: str,
    voice: Voice,
    audio_format: AudioFormat,
    speed: float,
) -> None:
    """Handle long text by splitting it into chunks and generating multiple files."""
    # Create client
    try:
        client = TTSClient(
            base_url=args.url, api_key=args.api_key, timeout=args.timeout, max_retries=args.retries
        )

        # Use the new long text method
        responses = client.generate_speech_long_text(
            text=text,
            voice=voice,
            response_format=audio_format,
            speed=speed,
            max_length=args.max_length,
            preserve_words=True,
            auto_combine=args.auto_combine,
        )

        if not responses:
            print("Error: No valid text chunks found after processing.", file=sys.stderr)
            sys.exit(1)
        if isinstance(responses, TTSResponse):
            combined_response = responses
            combined_response.save_to_file(args.output)
            print(f"Generated combined audio: {args.output}")
            return

        print(f"Generated {len(responses)} audio chunks")

        base_name, ext = os.path.splitext(args.output)

        for i, response in enumerate(responses, 1):
            if args.verbose:
                print(f"Saving chunk {i}/{len(responses)}...")

            if len(responses) == 1:
                output_file = args.output
            else:
                output_file = f"{base_name}_part{i:03d}{ext}"

            with open(output_file, "wb") as f:
                f.write(response.audio_data)

            print(f"Generated: {output_file}")

        if len(responses) > 1:
            print(f"\nGenerated {len(responses)} audio files from long text.")
            print(f"Files: {base_name}_part001{ext} to {base_name}_part{len(responses):03d}{ext}")

    except Exception as e:
        print(f"Error processing long text: {e}", file=sys.stderr)
        if args.verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)


def main() -> None:
    """Main CLI entry point."""
    parser = create_parser()
    args = parser.parse_args()

    # Get text input
    if args.text:
        text = args.text
    else:
        text = read_text_file(args.text_file)

    if not text:
        print("Error: No text provided.", file=sys.stderr)
        sys.exit(1)

    # Validate parameters
    speed = validate_speed(args.speed)
    voice = get_voice_enum(args.voice)
    audio_format = get_format_enum(args.format)

    # Create output directory if needed
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Check text length and handle accordingly
    text_length = len(text)
    validate_length = not args.no_length_validation

    if args.verbose:
        print(f"Text: {text[:50]}{'...' if len(text) > 50 else ''}")
        print(f"Text length: {text_length} characters")
        print(f"Max length: {args.max_length}")
        print(f"Length validation: {'enabled' if validate_length else 'disabled'}")
        print(f"Voice: {args.voice}")
        print(f"Format: {args.format}")
        print(f"Speed: {speed}")
        print(f"URL: {args.url}")
        print(f"Output: {args.output}")
        print()

    # Handle long text
    if text_length > args.max_length:
        if args.split_long_text:
            print(f"Text is {text_length} characters, splitting into chunks...")
            return handle_long_text(args, text, voice, audio_format, speed)
        elif validate_length:
            print(
                f"Error: Text is too long ({text_length} characters). "
                f"Maximum allowed is {args.max_length} characters.",
                file=sys.stderr,
            )
            print(
                "Use --split-long-text to automatically split the text, "
                "or --no-length-validation to disable this check.",
                file=sys.stderr,
            )
            sys.exit(1)

    # Create client
    try:
        client = TTSClient(
            base_url=args.url, api_key=args.api_key, timeout=args.timeout, max_retries=args.retries
        )

        if args.verbose:
            print("Generating speech...")

        # Generate speech
        response = client.generate_speech(
            text=text,
            voice=voice,
            response_format=audio_format,
            speed=speed,
            max_length=args.max_length,
            validate_length=validate_length,
        )

        # Save to file
        with open(args.output, "wb") as f:
            f.write(response.audio_data)

        print(f"Speech generated successfully: {args.output}")

    except NetworkException as e:
        print(f"Network error: {e}", file=sys.stderr)
        sys.exit(1)
    except APIException as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(1)
    except TTSException as e:
        print(f"TTS error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
