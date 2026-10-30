"""Non-destructive inspection geometry, relative to the original displayed PDF page.

Crop first, then rotate clockwise. Never changes an original, OCR cache, or fact.
The source page's own PDF rotation is already represented by its displayed rect.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class PageView:
    box: tuple[float, float, float, float] = (0, 0, 1, 1)
    rotation: int = 0

    def __post_init__(self):
        if (type(self.rotation) is not int or self.rotation not in (0, 90, 180, 270)):
            raise ValueError("INVALID_VIEW_ROTATION")
        if (not isinstance(self.box, (tuple, list)) or len(self.box) != 4
                or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in self.box)
                or self.box[0] >= self.box[2] or self.box[1] >= self.box[3]):
            raise ValueError("INVALID_VIEW_BOX")
        object.__setattr__(self, "box", tuple(self.box))

    def to_source(self, x, y):
        """Map a normalized displayed crop point back to the original page."""
        if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in (x, y)):
            raise ValueError("INVALID_VIEW_POINT")
        u, v = {0: (x, y), 90: (y, 1-x), 180: (1-x, 1-y), 270: (1-y, x)}[self.rotation]
        left, top, right, bottom = self.box
        return [left + u * (right-left), top + v * (bottom-top)]

    def metadata(self, page_id):
        origin = self.to_source(0, 0)
        right = self.to_source(1, 0)
        bottom = self.to_source(0, 1)
        return {"page_id": page_id, "source_box": list(self.box),
                "clockwise_rotation": self.rotation, "operation": "crop_then_rotate",
                "coordinates": "original_displayed_page_excluding_application_label",
                "view_corners_in_source": [self.to_source(x, y) for x, y in ((0,0), (1,0), (1,1), (0,1))],
                "view_to_source_matrix": [[right[0]-origin[0], bottom[0]-origin[0], origin[0]],
                                          [right[1]-origin[1], bottom[1]-origin[1], origin[1]],
                                          [0, 0, 1]],
                "original_unchanged": True}

    def apply(self, image):
        # Input has already been cropped by the PDF renderer. PIL rotate uses CCW.
        return image.rotate(-self.rotation, expand=True) if self.rotation else image
