import customtkinter as ctk
import tkinter as tk
import tkinter.font as tkfont
import threading
import pyte
import logging
import unicodedata
logger = logging.getLogger('ZeroSync.Terminal')
VIRTUAL_HEIGHT = 1000

class TerminalWidget(ctk.CTkTextbox):

    def __init__(self, master, on_input_callback=None, on_resize_callback=None, **kwargs):
        super().__init__(master, wrap='char', corner_radius=0, border_width=0, **kwargs)
        self._textbox.configure(insertbackground='white', insertwidth=2, blockcursor=False, padx=0, pady=0, borderwidth=0, highlightthickness=0)
        self.configure(state='normal', font=('Consolas', 13), fg_color='#1e1e1e', text_color='#d4d4d4')
        self.on_input = on_input_callback
        self.on_resize = on_resize_callback
        self._pyte_lock = threading.Lock()
        self.screen = pyte.HistoryScreen(80, VIRTUAL_HEIGHT, history=10000, ratio=0.5)
        self.stream = pyte.Stream(self.screen)
        self._last_rendered_hash = None
        self._cached_history_len = -1
        self._cached_history_lines = []
        self.term_font = tkfont.Font(family='Consolas', size=13)
        self.char_width = self.term_font.measure('M')
        self.char_height = self.term_font.metrics('linespace')
        self._pending_data = []
        self._is_ready = False
        self._render_job = None
        self._resize_job = None
        self._known_color_tags = set()
        self._setup_base_colors()
        self.bind('<Key>', self._on_key_press)
        self.bind('<Configure>', self._on_window_resize)
        self.bind('<Button-1>', self._on_mouse_press)
        self.bind('<ButtonRelease-1>', self._on_mouse_release)
        self.after(200, self._isolate_and_calibrate)

    def _setup_base_colors(self):
        colors = {'black': '#4C4C4C', 'red': '#E74C3C', 'green': '#2ECC71', 'brown': '#F1C40F', 'blue': '#3498DB', 'magenta': '#9B59B6', 'cyan': '#1ABC9C', 'white': '#ECF0F1', 'default': '#d4d4d4'}
        for name, hexcode in colors.items():
            tag_name = f'fg_{name}'
            self._textbox.tag_config(tag_name, foreground=hexcode)
            self._known_color_tags.add(tag_name)

    def feed(self, data: str):
        if not data:
            return
        if not self._is_ready:
            self._pending_data.append(data)
            return
        self.stream.feed(data)
        if self._render_job is None:
            self._render_job = self.after(50, self._render_screen)

    def _render_screen(self, jump_to_bottom_override=None):
        self._render_job = None
        if not self.winfo_exists():
            return
        try:
            top_index = self._textbox.index('@0,0')
            top_line = int(top_index.split('.')[0])
            last_line_index = self._textbox.index('end-1c')
            total_content_lines = int(last_line_index.split('.')[0])
            bottom_index = self._textbox.index(f'@0,{self._textbox.winfo_height()}')
            bottom_line = int(bottom_index.split('.')[0])
            is_fit_in_screen = total_content_lines <= bottom_line - top_line + 1
            is_scrolled_bottom = self._textbox.yview()[1] >= 0.99
            anchor_line = top_line
        except Exception:
            is_fit_in_screen = False
            is_scrolled_bottom = True
            anchor_line = 1
        if jump_to_bottom_override is True:
            should_stick_to_bottom = True
        elif jump_to_bottom_override is False:
            should_stick_to_bottom = False
        else:
            should_stick_to_bottom = is_fit_in_screen or is_scrolled_bottom
        with self._pyte_lock:
            raw_history = list(self.screen.history.top)
            current_history_len = len(raw_history)
            if current_history_len != self._cached_history_len:
                self._cached_history_lines = []
                for row in raw_history:
                    if isinstance(row, str):
                        self._cached_history_lines.append(row)
                    else:
                        self._cached_history_lines.append(''.join((row[x].data for x in range(len(row)))))
                self._cached_history_len = current_history_len
            virtual_buffer = list(self.screen.display)
            pyte_cursor_y = self.screen.cursor.y
            pyte_cursor_x = self.screen.cursor.x
            buffer_copy = {y: {x: self.screen.buffer[y][x] for x in range(self.screen.columns)} for y in range(len(virtual_buffer))}
            screen_columns = self.screen.columns
        max_content_idx = 0
        for i in range(len(virtual_buffer) - 1, -1, -1):
            if virtual_buffer[i].strip():
                max_content_idx = i
                break
        render_limit = max(max_content_idx, pyte_cursor_y) + 1
        active_lines = virtual_buffer[:render_limit]
        full_text_lines = self._cached_history_lines.copy()
        full_text_lines.extend(active_lines)
        processed_lines = []
        cursor_abs_row = len(full_text_lines) - len(active_lines) + pyte_cursor_y
        tk_cursor_x = pyte_cursor_x
        for i, line in enumerate(full_text_lines):
            clean_line = line.rstrip()
            if i == cursor_abs_row:
                if len(clean_line) < pyte_cursor_x:
                    clean_line += ' ' * (pyte_cursor_x - len(clean_line))
                current_w = 0
                tk_cursor_x = 0
                for c in clean_line:
                    if current_w >= pyte_cursor_x:
                        break
                    current_w += 2 if unicodedata.east_asian_width(c) in ('W', 'F', 'A') else 1
                    tk_cursor_x += 1
            processed_lines.append(clean_line)
        final_text = '\n'.join(processed_lines)
        current_hash = hash(final_text)
        if current_hash != self._last_rendered_hash:
            try:
                self._textbox.configure(state='normal')
                self.delete('1.0', 'end')
                self.insert('1.0', final_text)
                self._apply_ansi_colors(len(raw_history), render_limit, screen_columns, buffer_copy)
                self._last_rendered_hash = current_hash
            except Exception as e:
                logger.error(f'Render Text Error: {e}')
        try:
            ui_cursor_row = cursor_abs_row + 1
            mark_pos = f'{ui_cursor_row}.{tk_cursor_x}'
            self.mark_set('insert', mark_pos)
            if should_stick_to_bottom:
                self.see('end')
            else:
                total_lines_after = len(processed_lines)
                fraction = (anchor_line - 1) / max(1, total_lines_after)
                self._textbox.yview_moveto(fraction)
        except Exception as e:
            pass

    def _apply_ansi_colors(self, history_offset, render_limit, screen_columns, buffer_copy):
        for y in range(render_limit):
            row_data = buffer_copy[y]
            current_tag = None
            start_x = 0
            for x in range(screen_columns):
                char = row_data[x]
                fg = char.fg
                if fg != current_tag:
                    if current_tag != 'default' and current_tag is not None:
                        tag_name = f'fg_{current_tag}'
                        if tag_name not in self._known_color_tags:
                            try:
                                hex_c = f'#{current_tag}' if not current_tag.startswith('#') else current_tag
                                self._textbox.tag_config(tag_name, foreground=hex_c)
                                self._known_color_tags.add(tag_name)
                            except tk.TclError:
                                pass
                        tk_row = history_offset + y + 1
                        self._textbox.tag_add(tag_name, f'{tk_row}.{start_x}', f'{tk_row}.{x}')
                    current_tag = fg
                    start_x = x
            if current_tag != 'default' and current_tag is not None:
                tag_name = f'fg_{current_tag}'
                if tag_name not in self._known_color_tags:
                    try:
                        hex_c = f'#{current_tag}' if not current_tag.startswith('#') else current_tag
                        self._textbox.tag_config(tag_name, foreground=hex_c)
                        self._known_color_tags.add(tag_name)
                    except tk.TclError:
                        pass
                tk_row = history_offset + y + 1
                self._textbox.tag_add(tag_name, f'{tk_row}.{start_x}', f'{tk_row}.{screen_columns}')

    def _on_window_resize(self, event):
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(100, lambda: self._perform_delayed_resize(event.width, event.height))

    def _perform_delayed_resize(self, width, height, force=False):
        self._resize_job = None
        SCROLLBAR_WIDTH = 20
        ui_cols = max(20, (width - SCROLLBAR_WIDTH) // self.char_width)
        ui_rows = max(5, height // self.char_height)
        try:
            self.screen.resize(lines=VIRTUAL_HEIGHT, columns=ui_cols)
        except Exception as e:
            logger.error(f'Pyte resize error: {e}')
        if self.on_resize:
            self.on_resize(ui_cols, ui_rows)
        self._render_screen(jump_to_bottom_override=True)

    def _on_key_press(self, event):
        if not self.on_input:
            return 'break'
        send_str = ''
        key = event.keysym
        if event.state & 4 != 0:
            if len(key) == 1:
                code = ord(key.upper()) - 64
                if 1 <= code <= 26:
                    send_str = chr(code)
            elif key == 'space':
                send_str = '\x00'
            elif key == 'bracketleft':
                send_str = '\x1b'
            if key.lower() == 'c':
                if self.tag_ranges('sel'):
                    return
                else:
                    send_str = '\x03'
            elif key.lower() == 'v':
                try:
                    self.on_input(self.clipboard_get())
                    return 'break'
                except:
                    pass
        elif key in self.KEY_MAP:
            send_str = self.KEY_MAP[key]
        elif len(event.char) > 0:
            if ord(event.char) >= 32 or event.char in ('\r', '\n', '\t', '\x08'):
                send_str = event.char
        if send_str:
            self.on_input(send_str)
        return 'break'

    def _on_mouse_press(self, event):
        self.focus_set()

    def _on_mouse_release(self, event):
        self._selection_active = False
        self.focus_set()
        if self._render_job is None:
            self._render_screen()
        try:
            if self.tag_ranges('sel'):
                return
            click_index = self._textbox.index(f'@{event.x},{event.y}')
            click_row_str, click_col_str = click_index.split('.')
            click_col = int(click_col_str)
            cursor_index = self._textbox.index('insert')
            cursor_row_str, cursor_col_str = cursor_index.split('.')
            line_text = self._textbox.get(f'{click_row_str}.0', f'{click_row_str}.end')
            max_len = len(line_text)
            if click_col > max_len:
                click_col = max_len
            click_index = f'{click_row_str}.{click_col}'
            if abs(int(click_row_str) - int(cursor_row_str)) > 5:
                return
            if self._textbox.compare(click_index, '<', cursor_index):
                text_between = self._textbox.get(click_index, cursor_index)
                diff = len(text_between.replace('\n', ''))
                if 0 < diff < 500:
                    self.on_input('\x1b[D' * diff)
            elif self._textbox.compare(click_index, '>', cursor_index):
                text_between = self._textbox.get(cursor_index, click_index)
                diff = len(text_between.replace('\n', ''))
                if 0 < diff < 500:
                    self.on_input('\x1b[C' * diff)
        except Exception:
            pass

    def clear(self):
        self.screen.reset()
        self.screen.history.top.clear()
        self._render_screen()

    def _isolate_and_calibrate(self):
        if not self.winfo_viewable():
            self.after(200, self._isolate_and_calibrate)
            return
        try:
            self._textbox.configure(state='normal')
            self.delete('1.0', 'end')
            self.insert('1.0', '--- INITIALIZING TERMINAL ENVIRONMENT ---\nM')
            self.update_idletasks()
            bbox = self._textbox.bbox('2.0')
            if not bbox:
                self.after(200, self._isolate_and_calibrate)
                return
            self.char_width = bbox[2]
            self.char_height = bbox[3]
            self.delete('1.0', 'end')
            self._is_ready = True
            curr_w, curr_h = (self.winfo_width(), self.winfo_height())
            self._perform_delayed_resize(curr_w, curr_h, force=True)
            if self._pending_data:
                self.stream.feed(''.join(self._pending_data))
                self._pending_data = []
            self._render_screen()
        except Exception:
            self.after(500, self._isolate_and_calibrate)
    KEY_MAP = {'Return': '\r', 'BackSpace': '\x7f', 'Tab': '\t', 'Escape': '\x1b', 'Delete': '\x1b[3~', 'Up': '\x1b[A', 'Down': '\x1b[B', 'Right': '\x1b[C', 'Left': '\x1b[D', 'Home': '\x1b[H', 'End': '\x1b[F', 'Prior': '\x1b[5~', 'Next': '\x1b[6~', 'Insert': '\x1b[2~', 'F1': '\x1bOP', 'F2': '\x1bOQ', 'F3': '\x1bOR', 'F4': '\x1bOS', 'F5': '\x1b[15~', 'F6': '\x1b[17~', 'F7': '\x1b[18~', 'F8': '\x1b[19~', 'F9': '\x1b[20~', 'F10': '\x1b[21~', 'F11': '\x1b[23~', 'F12': '\x1b[24~'}