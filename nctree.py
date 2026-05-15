import netCDF4 as nc

def read_nc_file(file_path):
    # Open the NetCDF file
    dataset = nc.Dataset(file_path, mode='r')
    
    # Display basic information about the file
    print(f"NetCDF file: {file_path}")
    print(f"Dimensions: {dataset.dimensions.keys()}")
    print(f"Variables: {dataset.variables.keys()}")
    
    # Access specific variables
    for var in dataset.variables.keys():
        print(f"\nVariable '{var}' details:")
        print(f"\tDimensions: {dataset.variables[var].dimensions}")
        print(f"\tShape: {dataset.variables[var].shape}")
        print(f"\tData: {dataset.variables[var][:]}")  # Prints the variable data (may be large)
    
    # Close the dataset when done
    dataset.close()

# Example usage:
read_nc_file("/Users/marinf/Downloads/detector_example_files/xmap_2xfm_0001_2xfm3_0.nc")