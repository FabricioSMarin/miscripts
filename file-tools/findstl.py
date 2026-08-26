import os

def find_stl_files(start_path="/"):
    stl_files = []
    for root, dirs, files in os.walk(start_path):
        for file in files:
            if file.lower().endswith(".stl"):
                stl_files.append(os.path.join(root, file))
    return stl_files


if __name__ == "__main__":
    # Change this path to the root of your drive, e.g. "C:\\", "/Volumes/Extreme SSD", "/mnt/data"
    search_path = f"/Volumes/Extreme SSD"

    print(f"Searching for .stl files under: {search_path}")
    results = find_stl_files(search_path)

    print(f"\nFound {len(results)} .stl files:\n")
    for f in results:
        print(f)
