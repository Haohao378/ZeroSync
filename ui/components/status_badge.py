import customtkinter as ctk

class StatusBadge(ctk.CTkFrame):

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color='transparent', **kwargs)
        self.grid_columnconfigure(1, weight=1)
        self.canvas = ctk.CTkCanvas(self, width=14, height=14, bg=master._apply_appearance_mode(ctk.ThemeManager.theme['CTkFrame']['fg_color']), highlightthickness=0)
        self.canvas.grid(row=0, column=0, padx=(0, 8), pady=2)
        self.indicator = self.canvas.create_oval(2, 2, 12, 12, fill='gray', outline='')
        self.label = ctk.CTkLabel(self, text='未启动', font=('Roboto', 13, 'bold'))
        self.label.grid(row=0, column=1, sticky='w')

    def set_status(self, status: str):
        colors = {'stopped': ('#808080', '未启动'), 'running': ('#2ECC71', '实时同步中'), 'paused': ('#F1C40F', '已挂起/拉取中'), 'error': ('#E74C3C', '连接断开')}
        color, text = colors.get(status, colors['stopped'])
        self.canvas.itemconfig(self.indicator, fill=color)
        self.label.configure(text=text, text_color=color)