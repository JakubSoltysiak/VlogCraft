"""Double-clickable development viewer; never bundled with the editor."""
from qa_status import main
import sys
if __name__=='__main__':
    sys.argv.append('--view');main()
