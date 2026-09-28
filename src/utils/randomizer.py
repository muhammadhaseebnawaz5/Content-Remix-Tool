"""
Randomizer - Applies random parameters per video for duplicate prevention.
"""

import random
import hashlib
import json
from typing import Dict, Any, List, Optional, Tuple


class Randomizer:
    """Randomizes effect parameters per video."""

    def apply_randomization(self, config: Dict[str, Any], video_index: int) -> None:
        """Apply randomization to config for a specific video."""
        ai_remix = config.get("ai_remix", {})
        if not ai_remix.get("enabled", False) or not ai_remix.get("randomize", False):
            return

        effects = config.setdefault("effects", {})
        varied_count = 0

        # Seed random for reproducibility if needed, but we want uniqueness
        random.seed(video_index * 1337 + hash(config.get("project", {}).get("name", "")) % 10000)

        # Mirror
        if effects.get("mirror", {}).get("enabled", False) and effects["mirror"].get("randomize", False):
            effects["mirror"]["mode"] = random.choice(["horizontal", "vertical", "both", "alternate"])
            varied_count += 1

        # Zoom
        if effects.get("zoom", {}).get("enabled", False) and effects["zoom"].get("randomize", False):
            effects["zoom"]["mode"] = random.choice(["zoom_in", "zoom_out", "dynamic", "ken_burns"])
            effects["zoom"]["min_zoom"] = round(random.uniform(1.0, 1.2), 2)
            effects["zoom"]["max_zoom"] = round(random.uniform(1.3, 2.0), 2)
            varied_count += 1

        # Crop
        if effects.get("crop", {}).get("enabled", False) and effects["crop"].get("randomize", False):
            effects["crop"]["mode"] = random.choice(["center", "random"])
            effects["crop"]["aspect_ratio"] = random.choice(["16:9", "4:3", "1:1", "9:16", "3:2"])
            varied_count += 1

        # Rotation
        if effects.get("rotation", {}).get("enabled", False) and effects["rotation"].get("randomize", False):
            effects["rotation"]["mode"] = random.choice(["small", "large", "clockwise", "anticlockwise", "random"])
            varied_count += 1

        # Speed
        if effects.get("speed", {}).get("enabled", False) and effects["speed"].get("randomize", False):
            effects["speed"]["speed"] = random.choice([0.8, 0.9, 1.1, 1.2])
            varied_count += 1

        # Brightness
        if effects.get("brightness", {}).get("enabled", False) and effects["brightness"].get("randomize", False):
            r = effects["brightness"].get("range", [-0.2, 0.2])
            effects["brightness"]["value"] = round(random.uniform(r[0], r[1]), 3)
            varied_count += 1

        # Contrast
        if effects.get("contrast", {}).get("enabled", False) and effects["contrast"].get("randomize", False):
            r = effects["contrast"].get("range", [0.8, 1.5])
            effects["contrast"]["value"] = round(random.uniform(r[0], r[1]), 3)
            varied_count += 1

        # Saturation
        if effects.get("saturation", {}).get("enabled", False) and effects["saturation"].get("randomize", False):
            r = effects["saturation"].get("range", [0.5, 1.8])
            effects["saturation"]["value"] = round(random.uniform(r[0], r[1]), 3)
            varied_count += 1

        # Hue
        if effects.get("hue", {}).get("enabled", False) and effects["hue"].get("randomize", False):
            r = effects["hue"].get("range", [-30, 30])
            effects["hue"]["value"] = round(random.uniform(r[0], r[1]), 1)
            varied_count += 1

        # Sharpness
        if effects.get("sharpness", {}).get("enabled", False) and effects["sharpness"].get("randomize", False):
            r = effects["sharpness"].get("range", [0.5, 2.0])
            effects["sharpness"]["value"] = round(random.uniform(r[0], r[1]), 3)
            varied_count += 1

        # Noise
        if effects.get("noise", {}).get("enabled", False) and effects["noise"].get("randomize", False):
            effects["noise"]["mode"] = random.choice(["film_grain", "light", "random"])
            effects["noise"]["intensity"] = round(random.uniform(0.02, 0.12), 3)
            varied_count += 1

        # Motion blur
        if effects.get("motion_blur", {}).get("enabled", False) and effects["motion_blur"].get("randomize", False):
            effects["motion_blur"]["frames"] = random.randint(2, 5)
            varied_count += 1

        # Camera shake
        if effects.get("camera_shake", {}).get("enabled", False) and effects["camera_shake"].get("randomize", False):
            effects["camera_shake"]["intensity"] = random.choice(["small", "medium", "large"])
            varied_count += 1

        # Duplicate prevention: ensure minimum varied effects
        # NOTE: We no longer mutate here — the caller must call
        # get_forced_effects() first, show the user a consent dialog,
        # and then call apply_forced_variation() if approved.
        # (self._pending_forced is set so the caller can inspect it.)
        min_vary = ai_remix.get("min_effects_vary", 3)
        if ai_remix.get("duplicate_prevention", False) and varied_count < min_vary:
            needed = min_vary - varied_count
            self._pending_forced = self._collect_forced_effects(effects, needed)
        else:
            self._pending_forced = []

        # Reset random seed
        random.seed()

    def _collect_forced_effects(self, effects: Dict[str, Any], count: int) -> List[str]:
        """Return the list of effect names that *would* be force-enabled to meet
        the minimum variation count.  Does NOT mutate anything — callers must
        call apply_forced_variation() after obtaining user consent."""
        candidates = ["brightness", "contrast", "saturation", "hue", "sharpness", "noise"]
        will_force: List[str] = []
        for cand in candidates:
            if len(will_force) >= count:
                break
            eff = effects.get(cand, {})
            if not eff.get("enabled", False):
                will_force.append(cand)
        return will_force

    def get_pending_forced_effects(self) -> List[str]:
        """Return the list of effects that need to be force-enabled (set after
        apply_randomization() runs).  Empty list means no forcing is needed."""
        return list(getattr(self, "_pending_forced", []))

    def apply_forced_variation(self, effects: Dict[str, Any]) -> None:
        """Actually enable + mark-randomize + assign random values to the effects
        collected during apply_randomization(). Call this ONLY after the user has consented."""
        for cand in getattr(self, "_pending_forced", []):
            if cand not in effects:
                effects[cand] = {}
            effects[cand]["enabled"] = True
            effects[cand]["randomize"] = True
            if cand == "brightness":
                r = effects[cand].get("range", [-0.2, 0.2])
                effects[cand]["value"] = round(random.uniform(r[0], r[1]), 3)
            elif cand == "contrast":
                r = effects[cand].get("range", [0.8, 1.5])
                effects[cand]["value"] = round(random.uniform(r[0], r[1]), 3)
            elif cand == "saturation":
                r = effects[cand].get("range", [0.5, 1.8])
                effects[cand]["value"] = round(random.uniform(r[0], r[1]), 3)
            elif cand == "hue":
                r = effects[cand].get("range", [-30, 30])
                effects[cand]["value"] = round(random.uniform(r[0], r[1]), 1)
            elif cand == "sharpness":
                r = effects[cand].get("range", [0.5, 2.0])
                effects[cand]["value"] = round(random.uniform(r[0], r[1]), 3)
            elif cand == "noise":
                effects[cand]["mode"] = random.choice(["film_grain", "light", "random"])
                effects[cand]["intensity"] = round(random.uniform(0.02, 0.12), 3)
        self._pending_forced = []

    def generate_fingerprint(self, config: Dict[str, Any]) -> str:
        """Generate MD5 hash of active effects for uniqueness verification."""
        effects = config.get("effects", {})
        active = {}
        for k, v in effects.items():
            if isinstance(v, dict) and v.get("enabled", False):
                active[k] = {kk: vv for kk, vv in v.items() if kk != "randomize"}
        data = json.dumps(active, sort_keys=True)
        return hashlib.md5(data.encode()).hexdigest()
