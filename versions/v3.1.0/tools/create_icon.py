#!/usr/bin/env python3
"""
Create a simple application icon for the Payroll Processor.
"""

import os
from PIL import Image, ImageDraw, ImageFont

def create_app_icon():
    """Create a simple application icon."""
    # Create a 1024x1024 image for high resolution
    size = 1024
    img = Image.new('RGBA', (size, size), (70, 130, 180, 255))  # Steel blue background
    draw = ImageDraw.Draw(img)
    
    # Draw a document/invoice icon
    # Main document rectangle
    doc_x = size // 4
    doc_y = size // 6
    doc_w = size // 2
    doc_h = int(size * 0.7)
    
    # Document background
    draw.rectangle([doc_x, doc_y, doc_x + doc_w, doc_y + doc_h], 
                   fill=(255, 255, 255, 255), outline=(50, 50, 50, 255), width=8)
    
    # Folded corner
    corner_size = size // 12
    draw.polygon([
        (doc_x + doc_w - corner_size, doc_y),
        (doc_x + doc_w, doc_y + corner_size),
        (doc_x + doc_w - corner_size, doc_y + corner_size)
    ], fill=(220, 220, 220, 255))
    
    # Lines representing text
    line_x = doc_x + size // 20
    line_w = doc_w - size // 10
    line_h = size // 60
    
    for i in range(8):
        y = doc_y + size // 8 + i * size // 20
        if i < 7:  # Full lines
            draw.rectangle([line_x, y, line_x + line_w, y + line_h], 
                          fill=(100, 100, 100, 255))
        else:  # Shorter last line
            draw.rectangle([line_x, y, line_x + line_w // 2, y + line_h], 
                          fill=(100, 100, 100, 255))
    
    # Euro symbol overlay
    euro_size = size // 6
    euro_x = doc_x + doc_w - euro_size - size // 20
    euro_y = doc_y + doc_h - euro_size - size // 20
    
    # Euro symbol background circle
    draw.ellipse([euro_x - 10, euro_y - 10, euro_x + euro_size + 10, euro_y + euro_size + 10],
                fill=(34, 139, 34, 200))  # Green background
    
    # Try to use a system font, fallback to default
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", euro_size)
    except:
        font = ImageFont.load_default()
    
    # Draw Euro symbol
    draw.text((euro_x, euro_y), "€", fill=(255, 255, 255, 255), font=font)
    
    return img

def create_icns_file():
    """Create an .icns file for macOS."""
    # Generate the base icon
    base_icon = create_app_icon()
    
    # Icon sizes needed for .icns
    sizes = [16, 32, 64, 128, 256, 512, 1024]
    icon_dir = "/Users/tiktaknto/Desktop/payment processor/icon_temp"
    
    # Save different sizes
    for size in sizes:
        resized = base_icon.resize((size, size), Image.Resampling.LANCZOS)
        resized.save(f"{icon_dir}/icon_{size}x{size}.png")
    
    # Create iconset directory
    iconset_dir = f"{icon_dir}/AppIcon.iconset"
    os.makedirs(iconset_dir, exist_ok=True)
    
    # Copy files with proper naming for iconset
    icon_mappings = {
        16: "icon_16x16.png",
        32: ["icon_16x16@2x.png", "icon_32x32.png"],
        64: "icon_32x32@2x.png",
        128: ["icon_64x64@2x.png", "icon_128x128.png"],
        256: ["icon_128x128@2x.png", "icon_256x256.png"],
        512: ["icon_256x256@2x.png", "icon_512x512.png"],
        1024: "icon_512x512@2x.png"
    }
    
    for size, names in icon_mappings.items():
        source = f"{icon_dir}/icon_{size}x{size}.png"
        if isinstance(names, list):
            for name in names:
                os.system(f"cp '{source}' '{iconset_dir}/{name}'")
        else:
            os.system(f"cp '{source}' '{iconset_dir}/{names}'")
    
    # Convert to .icns using iconutil (macOS built-in tool)
    output_icns = "/Users/tiktaknto/Desktop/payment processor/app_icon.icns"
    os.system(f"iconutil -c icns '{iconset_dir}' -o '{output_icns}'")
    
    print(f"Created app icon: {output_icns}")
    
    # Clean up temporary files
    os.system(f"rm -rf '{icon_dir}'")

if __name__ == "__main__":
    try:
        create_icns_file()
    except ImportError:
        print("PIL (Pillow) not available. Creating a simple placeholder icon...")
        # Create a simple placeholder
        placeholder_path = "/Users/tiktaknto/Desktop/payment processor/app_icon.icns"
        # Use system default or create empty file as fallback
        with open(placeholder_path, 'w') as f:
            f.write("")  # Empty file - py2app will use default
        print(f"Created placeholder icon: {placeholder_path}")