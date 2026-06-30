import os

def main():
    input_list_file = "/Volumes/Extreme 4T/other/failist.txt"
    output_dir = "/Volumes/Extreme 4T/other/outputs"
    os.makedirs(output_dir, exist_ok=True)

    with open(input_list_file, "r") as f:
        files = [line.strip() for line in f if line.strip()]

    count = 1
    for filepath in files:
        if not os.path.exists(filepath):
            print(f"❌ File not found: {filepath}")
            continue

        if os.path.splitext(filepath)[1]:
            print(f"ℹ️ Skipping (already has extension): {filepath}")
            continue

        new_name = f"image_{count:04d}.jpeg"
        new_path = os.path.join(output_dir, new_name)

        try:
            os.rename(filepath, new_path)
            print(f"✅ Renamed: {filepath} → {new_path}")
            count += 1
        except Exception as e:
            print(f"❗ Failed to rename {filepath}: {e}")

    print(f"\n✅ Done! Renamed {count-1} files.")

if __name__ == "__main__":
    main()