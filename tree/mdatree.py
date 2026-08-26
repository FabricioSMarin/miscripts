import mdaio
import numpy as np

def read_mda_file(file_path):
    # Read the .mda file and return the data as a NumPy array
    data = mdaio.readmda(file_path)
    return data

# Example usage:
data = read_mda_file("/Users/marinf/Downloads/detector_example_files/2xfm_0001.mda")
print(data.shape)  # Check the shape of the loaded data
# print(data)        # Print the data (be careful with large files)