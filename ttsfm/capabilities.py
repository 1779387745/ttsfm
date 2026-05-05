"""System capabilities detection for TTSFM.

This module provides runtime detection of available features based on
system dependencies (primarily ffmpeg availability).
"""

from __future__ import annotations

import shutil
from typing import Dict, List, Optional


class SystemCapabilities:
    """Detect and report system capabilities.

    This class checks for the availability of optional dependencies
    (like ffmpeg) and reports which features are available in the
    current environment.
    """

    def __init__(self) -> None:
        """Initialize capabilities detection."""
        self.ffmpeg_available = shutil.which("ffmpeg") is not None

    def get_capabilities(self) -> Dict:
        """Get complete system capabilities report.

        Returns:
            Dict containing:
                - ffmpeg_available: bool
                - image_variant: "full" or "slim"
                - features: dict of feature availability
                - supported_formats: list of supported audio formats
        """
        return {
            "ffmpeg_available": self.ffmpeg_available,
            "image_variant": "full" if self.ffmpeg_available else "slim",
            "features": {
                "speed_adjustment": self.ffmpeg_available,
                "format_conversion": self.ffmpeg_available,
                "mp3_auto_combine": self.ffmpeg_available,
                "basic_formats": True,  # MP3, WAV always available
            },
            "supported_formats": self.get_supported_formats(),
        }

    def get_supported_formats(self) -> List[str]:
        """Get list of supported audio formats.

        Returns:
            List of format names (e.g., ["mp3", "wav", "opus", ...])
        """
        basic = ["mp3", "wav"]
        if self.ffmpeg_available:
            return basic + ["opus", "aac", "flac", "pcm"]
        return basic

    def requires_ffmpeg(self, feature: str) -> bool:
        """Check if a feature requires ffmpeg.

        Args:
            feature: Feature name or format name to check

        Returns:
            True if the feature requires ffmpeg, False otherwise
        """
        ffmpeg_features = {
            "speed_adjustment",
            "format_conversion",
            "mp3_auto_combine",
            "opus",
            "aac",
            "flac",
            "pcm",
        }
        return feature.lower() in ffmpeg_features

    def check_feature_available(self, feature: str) -> bool:
        """Check if a specific feature is available.

        Args:
            feature: Feature name to check

        Returns:
            True if feature is available, False otherwise
        """
        if not self.requires_ffmpeg(feature):
            return True
        return self.ffmpeg_available

    def get_unavailable_reason(self, feature: str) -> Optional[str]:
        """Get reason why a feature is unavailable.

        Args:
            feature: Feature name to check

        Returns:
            Error message if unavailable, None if available
        """
        if self.check_feature_available(feature):
            return None

        return (
            f"Feature '{feature}' requires ffmpeg. "
            "Use the full Docker image (dbcccc/ttsfm:latest) instead of the slim variant."
        )


# Global instance for easy access
_capabilities_instance: Optional[SystemCapabilities] = None


def get_capabilities() -> SystemCapabilities:
    """Get global SystemCapabilities instance.

    Returns:
        SystemCapabilities singleton instance
    """
    global _capabilities_instance
    if _capabilities_instance is None:
        _capabilities_instance = SystemCapabilities()
    return _capabilities_instance
