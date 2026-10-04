# Makes `import pii` work when pytest runs from staging/pii (rootdir conftest inside a package
# inserts the parent directory, staging/, into sys.path).
