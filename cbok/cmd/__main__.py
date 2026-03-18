import sys

if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "-m":
        sys.argv = ["cbok"] + sys.argv[3:]
    else:
        sys.argv = ["cbok"] + sys.argv[1:]
    from cbok.cmd.main import main
    sys.exit(main() or 0)
