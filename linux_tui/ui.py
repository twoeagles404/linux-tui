"""Classic blue-screen menus using dialog/whiptail, with a curses fallback."""
import os
import shutil
import subprocess
import tempfile


class TerminalUI:
    def __init__(self, backend='auto'):
        self.program = None
        if backend != 'curses':
            self.program = next((shutil.which(name) for name in ('dialog', 'whiptail') if shutil.which(name)), None)

    def invoke(self, title, arguments):
        size = shutil.get_terminal_size((100, 30))
        height, width = max(10, min(25, size.lines - 2)), max(30, min(88, size.columns - 4))
        # Preserve the actual terminal on stdout/stderr. newt (whiptail) draws
        # on stdout; capturing stdout would hide its entire interface.
        with tempfile.TemporaryFile(mode='w+', encoding='utf-8') as selection:
            command = [self.program, '--backtitle', 'Linux TUI - portable Linux administration',
                       '--title', title, '--output-fd', str(selection.fileno()), *arguments(height, width)]
            result = subprocess.run(command, pass_fds=(selection.fileno(),),
                                    env={**os.environ, 'NEWT_COLORS': 'root=white,blue'})
            selection.seek(0)
            return selection.read().strip() if result.returncode == 0 else None

    def menu(self, title, entries, prompt='Select an option:'):
        if self.program:
            flattened = [value for key, label in entries for value in (key, label)]
            return self.invoke(title, lambda h, w: ['--menu', prompt, str(h), str(w), str(max(3, h - 8)), *flattened])
        return self.curses_view(title, entries, prompt)

    def message(self, title, text):
        if self.program:
            # Dialog textboxes support long command output without losing scrollback.
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False) as file:
                file.write(text or '(No output)')
                path = file.name
            try:
                if os.path.basename(self.program) == 'dialog':
                    self.invoke(title, lambda h, w: ['--textbox', path, str(h), str(w)])
                else:
                    self.invoke(title, lambda h, w: ['--scrolltext', '--msgbox', text or '(No output)', str(h), str(w)])
            finally:
                os.unlink(path)
        else:
            self.curses_view(title, None, text or '(No output)')

    def confirm(self, title, text):
        return self.menu(title, [('no', 'Cancel'), ('yes', 'Apply these changes')], text) == 'yes'

    def curses_view(self, title, entries, prompt):
        import curses

        def screen(window):
            curses.curs_set(0)
            if curses.has_colors():
                curses.start_color()
                curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)
                curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_WHITE)
                curses.init_pair(3, curses.COLOR_WHITE, curses.COLOR_BLUE)
            selected, offset, cancel = 0, 0, False
            import textwrap
            while True:
                rows, columns = window.getmaxyx()
                window.bkgd(' ', curses.color_pair(1))
                window.erase()
                if rows < 12 or columns < 45:
                    window.addnstr(0, 0, 'Resize terminal to at least 45 columns x 12 rows; Esc exits.', max(1, columns - 1))
                    window.refresh()
                    if window.getch() in (27, ord('q')):
                        return None
                    continue
                height, width = min(25, rows - 2), min(88, columns - 4)
                top, left = (rows - height) // 2, (columns - width) // 2
                panel = window.derwin(height, width, top, left)
                panel.bkgd(' ', curses.color_pair(2))
                panel.erase()
                panel.box()
                panel.addnstr(0, max(2, (width - len(title)) // 2), title, width - 4, curses.color_pair(3))
                lines = textwrap.wrap(prompt, width - 6, replace_whitespace=False) if entries else [part for line in prompt.splitlines() for part in (textwrap.wrap(line, width - 6) or [''])]
                if entries:
                    panel.addnstr(2, 2, lines[0] if lines else '', width - 4)
                    visible = height - 8
                    offset = min(offset, selected)
                    offset = max(offset, selected - visible + 1)
                    for index, (key, label) in enumerate(entries[offset:offset + visible], offset):
                        panel.addnstr(4 + index - offset, 4, f'{key:>2}  {label}', width - 8,
                                      curses.color_pair(3) if index == selected and not cancel else curses.color_pair(2))
                else:
                    visible = height - 6
                    for index, line in enumerate(lines[offset:offset + visible]):
                        panel.addnstr(2 + index, 3, line, width - 6)
                buttons = '< OK >       < Cancel >' if entries else '< OK >   Up/Down to scroll'
                panel.addnstr(height - 3, max(2, (width - len(buttons)) // 2), buttons, width - 4,
                              curses.color_pair(3) if not cancel else curses.A_REVERSE)
                panel.addnstr(height - 2, 2, 'Arrows: move   Enter: select   Tab: buttons   Esc: back', width - 4)
                window.noutrefresh()
                panel.noutrefresh()
                curses.doupdate()
                key = window.getch()
                if key in (27,):
                    return None
                if key in (10, 13, curses.KEY_ENTER):
                    return None if cancel or not entries else entries[selected][0]
                if key == 9:
                    cancel = not cancel
                elif key in (curses.KEY_UP, ord('k')):
                    if entries:
                        selected = (selected - 1) % len(entries)
                    else:
                        offset = max(0, offset - 1)
                elif key in (curses.KEY_DOWN, ord('j')):
                    if entries:
                        selected = (selected + 1) % len(entries)
                    else:
                        offset = min(max(0, len(lines) - visible), offset + 1)
                elif entries and 0 <= key < 256:
                    match = next((i for i, item in enumerate(entries) if item[0] == chr(key)), None)
                    if match is not None:
                        selected, cancel = match, False
        return curses.wrapper(screen)
