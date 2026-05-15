import h5py

def print_h5_tree(name, obj, prefix=''):
    """Recursively print the structure of the HDF5 file with tree-like lines."""
    # Print current node
    print(f"{prefix}|__ {name}")
    
    if isinstance(obj, h5py.Group):
        # Determine new prefix for child nodes
        new_prefix = prefix + "    "  # Indent for children
        # Iterate through the group's members
        for i, (key, value) in enumerate(obj.items()):
            # For the last item, avoid adding "|"
            if i == len(obj) - 1:
                print_h5_tree(key, value, new_prefix)
            else:
                print_h5_tree(key, value, new_prefix + "|")

def display_h5_structure(file_path):
    """Open HDF5 file and display its tree structure."""
    with h5py.File(file_path, 'r') as f:
        print_h5_tree("/", f)

# Example usage:
# display_h5_structure("your_file.h5")
# display_h5_structure("/Users/marinf/Downloads/sample_scan_00011.h5")
display_h5_structure("/Users/marinf/Downloads/detector_example_files/eiger_2xfm_000001.h5")