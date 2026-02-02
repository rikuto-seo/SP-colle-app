def build_image_path(member, costume, type_, group_key):
    filename = f"{member}_{costume}_{type_}.jpg"
    return f"member_images/{group_key}/{member}/{filename}"
