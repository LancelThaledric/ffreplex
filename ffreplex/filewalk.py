""""""

import os
from re import Pattern


def list_files(folder, pattern: Pattern[str]):
    result = []
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            if pattern.search(path):
                result.append(path)
        else:
            result.extend(list_files(path, pattern))
    return result
