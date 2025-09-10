import sys
import os
from uploader.main import main

# This ensures the 'uploader' package can be found
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

if __name__ == '__main__':
    main()