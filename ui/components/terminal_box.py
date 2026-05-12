import queue
import customtkinter as ctk
from datetime import datetime

class TerminalBox(ctk.CTkFrame):

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color='transparent', **kwargs)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.textbox = ctk.CTkTextbox(self, font=('Consolas', 13), fg_color='#1E1E1E', text_color='#A9B7C6', wrap='word')
        self.textbox.grid(row=0, column=0, sticky='nsew')
        self.textbox.insert('0.0', 'ZeroSync Engine CLI initialized.\n')
        self.textbox.tag_config('ERROR', foreground='#E74C3C')
        self.textbox.tag_config('CRITICAL', foreground='#9B59B6')
        self.textbox.tag_config('WARN', foreground='#F39C12')
        self.textbox.tag_config('INFO', foreground='#2ECC71')
        self.textbox.tag_config('DEBUG', foreground='#808080')
        self.textbox.configure(state='disabled')
        self.msg_queue = queue.Queue()
        self._poll_queue()

    def append_log(self, text: str, level: str='INFO'):
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        formatted_msg = f'[{timestamp}] [{level}] {text}'
        self.msg_queue.put((formatted_msg, level))

    def _poll_queue(self):
        try:
            import queue
            msgs_to_process = []
            for _ in range(500):
                try:
                    msgs_to_process.append(self.msg_queue.get_nowait())
                except queue.Empty:
                    break
            if msgs_to_process:
                self.textbox.configure(state='normal')
                for msg, level in msgs_to_process:
                    tag = level.upper() if level.upper() in ['ERROR', 'CRITICAL', 'WARN', 'INFO', 'DEBUG'] else None
                    if tag:
                        self.textbox.insert('end', msg + '\n', tag)
                    else:
                        self.textbox.insert('end', msg + '\n')
                self.textbox.see('end')
                self.textbox.configure(state='disabled')
        except Exception:
            pass
        finally:
            self.after(100, self._poll_queue)

    def clear(self):
        self.textbox.configure(state='normal')
        self.textbox.delete('1.0', 'end')
        self.textbox.insert('0.0', 'Terminal cleared.\n')
        self.textbox.configure(state='disabled')