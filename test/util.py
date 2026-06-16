from pathlib import Path
from djevops.util import git

def commit(file_path, message):
    if isinstance(file_path, Path):
        file_path = str(file_path)
    git('add', file_path)
    git('commit', '-m', message)
