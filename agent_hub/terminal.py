"""Keep menu keystrokes inside curses, including unassigned Ctrl combinations."""
import curses


def prepare_input(screen):
    # cbreak leaves Ctrl-S/Ctrl-Q flow control and Ctrl-Z suspension to the tty.
    # Raw mode delivers them as ordinary keys, so an unknown shortcut cannot
    # silently stop rendering or suspend the entire hub process.
    for configure in (curses.raw, curses.noecho):
        try:
            configure()
        except curses.error:
            pass
    try:
        curses.curs_set(0)
        curses.set_escdelay(25)
    except curses.error:
        pass
    screen.keypad(True)


def read_key(screen):
    prepare_input(screen)
    key = screen.get_wch()
    if key == '\x03':
        # Preserve Ctrl-C exit semantics now that the tty no longer raises SIGINT.
        raise KeyboardInterrupt
    return key
