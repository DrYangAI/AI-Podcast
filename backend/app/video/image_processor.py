"""Image preprocessing for video composition."""

from pathlib import Path

from PIL import Image


class ImageProcessor:
    """Normalize images for video composition."""

    def prepare_for_video(self, image_path: Path, target_width: int,
                          target_height: int, output_path: Path,
                          mode: str = "cover") -> Path:
        """Resize and pad/crop image to exact target dimensions."""
        img = Image.open(image_path)

        if mode == "cover":
            scale = max(target_width / img.width, target_height / img.height)
            new_size = (int(img.width * scale), int(img.height * scale))
            img = img.resize(new_size, Image.LANCZOS)
            left = (img.width - target_width) // 2
            top = (img.height - target_height) // 2
            img = img.crop((left, top, left + target_width, top + target_height))
        elif mode == "contain":
            img.thumbnail((target_width, target_height), Image.LANCZOS)
            new_img = Image.new("RGB", (target_width, target_height), (0, 0, 0))
            paste_x = (target_width - img.width) // 2
            paste_y = (target_height - img.height) // 2
            new_img.paste(img, (paste_x, paste_y))
            img = new_img

        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(output_path, quality=95)
        return output_path

    @staticmethod
    def get_resolution(aspect_ratio: str) -> tuple[int, int]:
        mapping = {
            "16:9": (1920, 1080),
            "9:16": (1080, 1920),
            "1:1": (1080, 1080),
        }
        return mapping.get(aspect_ratio, (1920, 1080))
