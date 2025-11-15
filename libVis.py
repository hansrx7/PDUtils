#!/usr/bin/env python3

"""
.lib File Visualizer
Visualizes timing arcs from Liberty (.lib) files with interactive GUI.
Supports comparing 2-4 cells with rise/fall selection per cell.
"""

# --- Environment / backend setup (must come BEFORE tkinter/matplotlib imports) ---
import os
os.environ["TK_SILENCE_DEPRECATION"] = "1"  # Silence Tk warnings on macOS

import sys
import matplotlib
matplotlib.use("TkAgg")  # Ensure we're using TkAgg backend for embedding in Tk

# --- Standard imports ---
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np


class LibParser:
    """Parser for Liberty (.lib) files."""
    
    def __init__(self, filepath):
        self.filepath = filepath
        self.cells = {}
        self.index1 = None
        self.index2 = None
        self.parse()
    
    def parse(self):
        """Parse the .lib file and extract cell information."""
        with open(self.filepath, 'r') as f:
            content = f.read()
        
        # Extract index values from template
        index1_patterns = [
            r'index_1\s*\(["\']([^"\']+)["\']\)',  # With quotes
            r'index_1\s*\(([^)]+)\)',             # Without quotes
        ]
        index2_patterns = [
            r'index_2\s*\(["\']([^"\']+)["\']\)',  # With quotes
            r'index_2\s*\(([^)]+)\)',             # Without quotes
        ]
        
        for pattern in index1_patterns:
            index1_match = re.search(pattern, content)
            if index1_match:
                index_str = index1_match.group(1).strip()
                self.index1 = [float(x.strip()) for x in index_str.split(',') if x.strip()]
                break
        
        for pattern in index2_patterns:
            index2_match = re.search(pattern, content)
            if index2_match:
                index_str = index2_match.group(1).strip()
                self.index2 = [float(x.strip()) for x in index_str.split(',') if x.strip()]
                break
        
        # Find all cells
        cell_pattern = r'cell\s*\(([^)]+)\)\s*\{'
        cell_matches = list(re.finditer(cell_pattern, content))
        
        for match in cell_matches:
            cell_name = match.group(1).strip()
            cell_start = match.end()
            
            # Find matching closing brace
            brace_count = 1
            i = cell_start
            while i < len(content) and brace_count > 0:
                if content[i] == '{':
                    brace_count += 1
                elif content[i] == '}':
                    brace_count -= 1
                i += 1
            
            cell_content = content[cell_start:i-1]
            self.cells[cell_name] = self._parse_cell(cell_name, cell_content)
    
    def _parse_cell(self, cell_name, content):
        """Parse a single cell's content."""
        cell_data = {
            'name': cell_name,
            'pins': {},
            'output_pins': []
        }
        
        # Find all pins
        pin_pattern = r'pin\s*\(([^)]+)\)\s*\{'
        pin_matches = list(re.finditer(pin_pattern, content))
        
        for match in pin_matches:
            pin_name = match.group(1).strip()
            pin_start = match.end()
            
            brace_count = 1
            i = pin_start
            while i < len(content) and brace_count > 0:
                if content[i] == '{':
                    brace_count += 1
                elif content[i] == '}':
                    brace_count -= 1
                i += 1
            
            pin_content = content[pin_start:i-1]
            pin_data = self._parse_pin(pin_name, pin_content)
            
            if pin_data:
                cell_data['pins'][pin_name] = pin_data
                if pin_data.get('direction') == 'output':
                    cell_data['output_pins'].append(pin_name)
        
        return cell_data
    
    def _parse_pin(self, pin_name, content):
        """Parse a single pin's content."""
        pin_data = {'name': pin_name}
        
        # Check direction
        dir_match = re.search(r'direction\s*:\s*(\w+)', content)
        if dir_match:
            pin_data['direction'] = dir_match.group(1).strip()
        else:
            return None
        
        # If input pin, get capacitance
        if pin_data['direction'] == 'input':
            cap_match = re.search(r'capacitance\s*:\s*([\d.]+)', content)
            if cap_match:
                pin_data['capacitance'] = float(cap_match.group(1))
        
        # If output pin, parse timing arcs
        if pin_data['direction'] == 'output':
            timing_blocks = self._parse_timing_blocks(content)
            pin_data['timing'] = timing_blocks
            
            # Get function
            func_match = re.search(r'function\s*:\s*"([^"]+)"', content)
            if func_match:
                pin_data['function'] = func_match.group(1)
        
        return pin_data
    
    def _parse_timing_blocks(self, content):
        """Parse timing blocks from pin content."""
        timing_blocks = []
        
        # Find all timing() blocks
        timing_pattern = r'timing\s*\(\s*\)\s*\{'
        timing_matches = list(re.finditer(timing_pattern, content))
        
        for match in timing_matches:
            timing_start = match.end()
            
            brace_count = 1
            i = timing_start
            while i < len(content) and brace_count > 0:
                if content[i] == '{':
                    brace_count += 1
                elif content[i] == '}':
                    brace_count -= 1
                i += 1
            
            timing_content = content[timing_start:i-1]
            timing_data = self._parse_timing_block(timing_content)
            if timing_data:
                timing_blocks.append(timing_data)
        
        return timing_blocks
    
    def _parse_timing_block(self, content):
        """Parse a single timing block."""
        timing_data = {}
        
        # Get related_pin
        related_match = re.search(r'related_pin\s*:\s*"([^"]+)"', content)
        if related_match:
            related_pins = related_match.group(1).strip().split()
            timing_data['related_pin'] = related_pins
        
        # Get timing_type
        type_match = re.search(r'timing_type\s*:\s*(\w+)', content)
        if type_match:
            timing_data['timing_type'] = type_match.group(1).strip()
        
        # Parse timing arcs (cell_rise, cell_fall, rise_transition, fall_transition)
        arc_types = ['cell_rise', 'cell_fall', 'rise_transition', 'fall_transition']
        timing_data['arcs'] = {}
        
        for arc_type in arc_types:
            # Pattern to match arc_type with values() - handle multi-line
            arc_pattern = rf'{arc_type}\s*\([^)]+\)\s*\{{[^{{}}]*values\s*\(["\']([^"\']*)["\']\)'
            arc_match = re.search(arc_pattern, content, re.DOTALL)
            
            if not arc_match:
                # Try without quotes - match until closing paren with brace balancing
                arc_start_pattern = rf'{arc_type}\s*\([^)]+\)\s*\{{[^{{}}]*values\s*\('
                start_match = re.search(arc_start_pattern, content, re.DOTALL)
                if start_match:
                    start_pos = start_match.end()
                    paren_count = 1
                    i = start_pos
                    while i < len(content) and paren_count > 0:
                        if content[i] == '(':
                            paren_count += 1
                        elif content[i] == ')':
                            paren_count -= 1
                        i += 1
                    if paren_count == 0:
                        values_str = content[start_pos:i-1].strip()
                        values_str = values_str.strip('"').strip("'").strip()
                        values = self._parse_matrix_values(values_str)
                        if values is not None:
                            timing_data['arcs'][arc_type] = values
                        continue
            
            if arc_match:
                values_str = arc_match.group(1).strip()
                values = self._parse_matrix_values(values_str)
                if values is not None:
                    timing_data['arcs'][arc_type] = values
        
        return timing_data if timing_data.get('related_pin') else None
    
    def _parse_matrix_values(self, values_str):
        """Parse 7x7 matrix values from string."""
        values_str = values_str.strip()
        
        # Try to split by commas first
        all_values = []
        for part in values_str.split(','):
            part = part.strip()
            if part:
                for val in part.split():
                    val = val.strip()
                    if val:
                        try:
                            all_values.append(float(val))
                        except ValueError:
                            pass
        
        if len(all_values) == 49:
            return np.array(all_values).reshape(7, 7)
        
        # Try parsing by rows
        lines = [line.strip() for line in values_str.replace('\n', ',').split(',') if line.strip()]
        if len(lines) >= 49:
            all_values = []
            for line in lines:
                for val in re.findall(r'-?\d+\.?\d*', line):
                    try:
                        all_values.append(float(val))
                    except ValueError:
                        pass
            
            if len(all_values) == 49:
                return np.array(all_values).reshape(7, 7)
        
        # Last attempt: extract all numbers
        numbers = re.findall(r'-?\d+\.?\d*', values_str)
        if len(numbers) == 49:
            try:
                all_values = [float(n) for n in numbers]
                return np.array(all_values).reshape(7, 7)
            except ValueError:
                pass
        
        return None


class LibVisualizer:
    """Main GUI application for visualizing .lib timing arcs."""
    
    def __init__(self, root):
        self.root = root
        self.root.title(".lib File Timing Arc Visualizer")
        self.root.geometry("1400x900")
        
        self.lib_parser = None
        self.selected_cells = []  # List of dicts: {cell_name, pin_name, input_name, arc_type}
        self.input_data = []      # Store input data for listbox items
        self.max_cells = 4
        self.min_cells = 2
        
        self.fig = None
        self.ax = None
        self.canvas = None
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup the user interface."""
        try:
            # Menu bar
            menubar = tk.Menu(self.root)
            self.root.config(menu=menubar)
            file_menu = tk.Menu(menubar, tearoff=0)
            menubar.add_cascade(label="File", menu=file_menu)
            file_menu.add_command(label="Open .lib file...", command=self._load_file, accelerator="Ctrl+O")
            file_menu.add_separator()
            file_menu.add_command(label="Exit", command=self.root.quit, accelerator="Ctrl+Q")
            
            self.root.bind('<Control-o>', lambda e: self._load_file())
            self.root.bind('<Control-q>', lambda e: self.root.quit())
        except Exception as e:
            print(f"Error setting up menu: {e}")
            import traceback
            traceback.print_exc()
        
        # Top frame
        top_frame = ttk.Frame(self.root, padding="10")
        top_frame.pack(fill=tk.X)
        ttk.Button(top_frame, text="Load .lib File", command=self._load_file).pack(side=tk.LEFT, padx=5)
        self.file_label = ttk.Label(top_frame, text="No file loaded")
        self.file_label.pack(side=tk.LEFT, padx=10)
        
        # Main frame
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        main_frame.grid_columnconfigure(1, weight=1)
        main_frame.grid_rowconfigure(0, weight=1)
        
        # Left panel
        self.left_panel = ttk.Frame(main_frame, width=380, relief='sunken', borderwidth=1)
        self.left_panel.grid(row=0, column=0, sticky='ns', padx=(0, 10))
        self.left_panel.grid_propagate(False)
        
        # Cell list
        ttk.Label(self.left_panel, text="Cells", font=("Arial", 12, "bold")).pack(anchor=tk.W, pady=(0, 5))
        cell_container = ttk.Frame(self.left_panel)
        cell_container.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        scrollbar_cells = ttk.Scrollbar(cell_container, orient=tk.VERTICAL)
        self.cell_listbox = tk.Listbox(
            cell_container, yscrollcommand=scrollbar_cells.set,
            bg='white', fg='black', selectbackground='#007aff', selectforeground='white',
            height=12, exportselection=False
        )
        scrollbar_cells.config(command=self.cell_listbox.yview)
        self.cell_listbox.grid(row=0, column=0, sticky='nsew')
        scrollbar_cells.grid(row=0, column=1, sticky='ns')
        cell_container.grid_rowconfigure(0, weight=1)
        cell_container.grid_columnconfigure(0, weight=1)
        self.cell_listbox.bind('<<ListboxSelect>>', self._on_cell_select)
        self.cell_listbox.insert(tk.END, "Load a .lib file...")
        
        # Input pins
        ttk.Label(self.left_panel, text="Input Pins", font=("Arial", 12, "bold")).pack(anchor=tk.W, pady=(0, 5))
        input_container = ttk.Frame(self.left_panel)
        input_container.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        scrollbar_inputs = ttk.Scrollbar(input_container, orient=tk.VERTICAL)
        self.input_listbox = tk.Listbox(
            input_container, yscrollcommand=scrollbar_inputs.set,
            bg='white', fg='black', selectbackground='#007aff', selectforeground='white',
            height=8, exportselection=False
        )
        scrollbar_inputs.config(command=self.input_listbox.yview)
        self.input_listbox.grid(row=0, column=0, sticky='nsew')
        scrollbar_inputs.grid(row=0, column=1, sticky='ns')
        input_container.grid_rowconfigure(0, weight=1)
        input_container.grid_columnconfigure(0, weight=1)
        self.input_listbox.bind('<<ListboxSelect>>', self._on_input_select)
        self.input_listbox.insert(tk.END, "Select cell first...")
        
        # Arc type
        ttk.Label(self.left_panel, text="Timing Arc Type", font=("Arial", 12, "bold")).pack(anchor=tk.W, pady=(10, 5))
        self.arc_frame = ttk.Frame(self.left_panel)
        self.arc_frame.pack(fill=tk.X, pady=(0, 10))
        self.arc_var = tk.StringVar(value="cell_rise")
        for text in ["cell_rise", "cell_fall", "rise_transition", "fall_transition"]:
            ttk.Radiobutton(self.arc_frame, text=text, variable=self.arc_var, value=text).pack(anchor=tk.W)
        
        # Transition index
        ttk.Label(self.left_panel, text="Input Transition Index", font=("Arial", 12, "bold")).pack(anchor=tk.W, pady=(10, 5))
        trans_frame = ttk.Frame(self.left_panel)
        trans_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(trans_frame, text="Row (0-6):").pack(side=tk.LEFT)
        self.transition_var = tk.IntVar(value=3)
        # IMPORTANT: use tk.Spinbox instead of ttk.Spinbox (ttk.Spinbox not available on older macOS Tk/Tcl 8.5)
        # tk.Spinbox syntax: from_, to, textvariable, width
        try:
            spinbox = tk.Spinbox(trans_frame, from_=0, to=6, textvariable=self.transition_var, width=5)
            spinbox.pack(side=tk.LEFT, padx=5)
        except Exception as e:
            print(f"Warning: Could not create Spinbox: {e}")
            # Fallback: use a simple Entry widget
            entry = tk.Entry(trans_frame, textvariable=self.transition_var, width=5)
            entry.pack(side=tk.LEFT, padx=5)
        
        # Buttons
        ttk.Button(self.left_panel, text="Add to Comparison", command=self._add_to_comparison).pack(fill=tk.X, pady=(10, 5))
        ttk.Label(self.left_panel, text="Selected Cells (2-4)", font=("Arial", 12, "bold")).pack(anchor=tk.W, pady=(5, 5))
        self.selected_frame = ttk.Frame(self.left_panel)
        self.selected_frame.pack(fill=tk.X, pady=(0, 5))
        
        button_frame = ttk.Frame(self.left_panel)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(button_frame, text="Plot Timing Arcs", command=self._plot_arcs).pack(fill=tk.X, pady=2)
        ttk.Button(button_frame, text="Clear All", command=self._clear_all).pack(fill=tk.X, pady=2)
        
        # Right panel
        self.right_panel = ttk.Frame(main_frame)
        self.right_panel.grid(row=0, column=1, sticky='nsew')
        
        # Placeholder before Matplotlib initializes
        self.placeholder_label = ttk.Label(
            self.right_panel, 
            text="Plot area\n\nMatplotlib will initialize\nwhen you create your first plot.",
            font=("Arial", 12),
            justify=tk.CENTER
        )
        self.placeholder_label.pack(expand=True, fill=tk.BOTH)
        
        if sys.platform == 'darwin':
            self.root.minsize(1200, 700)
        
        # Final update to ensure everything is visible
        try:
            self.root.update_idletasks()
        except Exception as e:
            print(f"Warning during final UI update: {e}")
    
    def _load_file(self):
        """Load a .lib file via file dialog."""
        filepath = filedialog.askopenfilename(
            title="Select .lib file",
            filetypes=[("Liberty files", "*.lib"), ("All files", "*.*")]
        )
        
        if filepath:
            self._load_file_from_path(filepath)
    
    def _load_file_from_path(self, filepath):
        """Load a .lib file from the given path."""
        try:
            self.lib_parser = LibParser(filepath)
            
            self.file_label.config(text=f"Loaded: {os.path.basename(filepath)}")
            
            self.selected_cells = []
            self.input_data = []
            self.input_listbox.delete(0, tk.END)
            
            self._update_cell_list()
            self._update_selected_display()
            
            if self.ax and self.canvas:
                self.ax.clear()
                self.ax.set_xlabel("Output Net Capacitance (fF)", fontsize=11)
                self.ax.set_ylabel("Delay/Transition Time (ns)", fontsize=11)
                self.ax.set_title("Timing Arc Comparison", fontsize=12, fontweight='bold')
                self.ax.grid(True, alpha=0.3)
                self.canvas.draw()
            
            self.root.update_idletasks()
            
            num_cells = len(self.lib_parser.cells) if self.lib_parser else 0
            messagebox.showinfo("Success", f"Loaded {num_cells} cells")
        except Exception as e:
            import traceback
            error_msg = f"Failed to load file:\n{str(e)}\n\n{traceback.format_exc()}"
            messagebox.showerror("Error", error_msg)
    
    def _update_cell_list(self):
        """Update the cell listbox with parsed cells."""
        if not self.lib_parser or not self.lib_parser.cells:
            return
        
        self.cell_listbox.delete(0, tk.END)
        
        cell_names = sorted(self.lib_parser.cells.keys())
        for cell_name in cell_names:
            self.cell_listbox.insert(tk.END, cell_name)
        
        self.root.update_idletasks()
        
        self.input_listbox.delete(0, tk.END)
        self.input_data = []
    
    def _on_cell_select(self, event):
        """Handle cell selection."""
        selection = self.cell_listbox.curselection()
        if not selection or not self.lib_parser:
            return
        
        cell_name = self.cell_listbox.get(selection[0])
        cell_data = self.lib_parser.cells.get(cell_name)
        if not cell_data:
            return
        
        self.input_listbox.delete(0, tk.END)
        self.input_data = []
        
        for output_pin in cell_data.get('output_pins', []):
            pin_data = cell_data['pins'].get(output_pin)
            if pin_data and pin_data.get('timing'):
                for timing_block in pin_data['timing']:
                    related_pins = timing_block.get('related_pin', [])
                    for related_pin in related_pins:
                        display_name = f"{output_pin} -> {related_pin}"
                        self.input_listbox.insert(tk.END, display_name)
                        self.input_data.append({
                            'cell_name': cell_name,
                            'output_pin': output_pin,
                            'input_name': related_pin
                        })
    
    def _on_input_select(self, event):
        """Handle input pin selection (no-op; selection handled when adding)."""
        pass
    
    def _add_to_comparison(self):
        """Add selected cell/input/arc to comparison."""
        if not self.lib_parser:
            messagebox.showwarning("Warning", "Please load a .lib file first")
            return
        
        cell_selection = self.cell_listbox.curselection()
        input_selection = self.input_listbox.curselection()
        
        if not cell_selection or not input_selection:
            messagebox.showwarning("Warning", "Please select a cell and an input pin")
            return
        
        if len(self.selected_cells) >= self.max_cells:
            messagebox.showwarning("Warning", f"Maximum {self.max_cells} cells allowed in comparison")
            return
        
        cell_name = self.cell_listbox.get(cell_selection[0])
        
        if input_selection[0] >= len(self.input_data):
            messagebox.showwarning("Warning", "Invalid input selection")
            return
        
        input_info = self.input_data[input_selection[0]]
        output_pin = input_info['output_pin']
        input_name = input_info['input_name']
        arc_type = self.arc_var.get()
        
        if cell_name != input_info['cell_name']:
            return
        
        for existing in self.selected_cells:
            if (existing['cell_name'] == cell_name and 
                existing['output_pin'] == output_pin and 
                existing['input_name'] == input_name and 
                existing['arc_type'] == arc_type):
                messagebox.showinfo("Info", "This combination is already selected")
                return
        
        cell_data = self.lib_parser.cells.get(cell_name)
        if not cell_data:
            return
        
        pin_data = cell_data['pins'].get(output_pin)
        if not pin_data or not pin_data.get('timing'):
            return
        
        arc_found = False
        for timing_block in pin_data['timing']:
            if input_name in timing_block.get('related_pin', []):
                if arc_type in timing_block.get('arcs', {}):
                    arc_found = True
                    break
        
        if not arc_found:
            messagebox.showwarning("Warning", f"Arc type '{arc_type}' not found for this path")
            return
        
        self.selected_cells.append({
            'cell_name': cell_name,
            'output_pin': output_pin,
            'input_name': input_name,
            'arc_type': arc_type
        })
        
        self._update_selected_display()
    
    def _update_selected_display(self):
        """Update the selected cells display."""
        for widget in self.selected_frame.winfo_children():
            widget.destroy()
        
        if not self.selected_cells:
            ttk.Label(self.selected_frame, text="No cells selected", foreground="gray").pack(anchor=tk.W)
            return
        
        for i, sel in enumerate(self.selected_cells):
            frame = ttk.Frame(self.selected_frame)
            frame.pack(fill=tk.X, pady=2)
            
            label_text = f"{sel['cell_name']}\n{sel['output_pin']} -> {sel['input_name']}\n{sel['arc_type']}"
            label = ttk.Label(frame, text=label_text, font=("Arial", 9))
            label.pack(side=tk.LEFT, padx=5)
            
            ttk.Button(frame, text="Remove", width=8, 
                       command=lambda idx=i: self._remove_from_comparison(idx)).pack(side=tk.RIGHT, padx=5)
    
    def _remove_from_comparison(self, index):
        """Remove a cell from comparison."""
        if 0 <= index < len(self.selected_cells):
            self.selected_cells.pop(index)
            self._update_selected_display()
    
    def _initialize_matplotlib(self):
        """Initialize matplotlib canvas lazily (only when needed)."""
        if self.fig and self.ax and self.canvas:
            return True
        
        try:
            if self.placeholder_label:
                self.placeholder_label.destroy()
                self.placeholder_label = None
            
            dpi = 100
            if sys.platform == 'darwin':
                try:
                    scale = self.root.tk.call('tk', 'scaling')
                    if scale and float(scale) > 1.0:
                        dpi = int(100 * float(scale))
                except Exception:
                    dpi = 100
            
            self.fig, self.ax = plt.subplots(figsize=(9, 6), dpi=dpi, facecolor='white')
            self.fig.patch.set_facecolor('white')
            
            self.canvas = FigureCanvasTkAgg(self.fig, self.right_panel)
            canvas_widget = self.canvas.get_tk_widget()
            canvas_widget.pack(fill=tk.BOTH, expand=True)
            
            self.ax.set_xlabel("Output Net Capacitance (fF)")
            self.ax.set_ylabel("Delay/Transition Time (ns)")
            self.ax.set_title("Timing Arc Comparison")
            self.ax.grid(True, alpha=0.3)
            
            def safe_draw():
                try:
                    if self.canvas:
                        self.canvas.draw()
                except Exception as e:
                    print(f"Canvas draw error: {e}")
            
            self.root.after(100, safe_draw)
            return True
        
        except Exception as e:
            import traceback
            print(f"Error initializing matplotlib: {e}")
            traceback.print_exc()
            messagebox.showerror("Error", f"Failed to initialize matplotlib:\n{str(e)}")
            return False
    
    def _plot_arcs(self):
        """Plot the selected timing arcs."""
        if not self.lib_parser:
            messagebox.showwarning("Warning", "Please load a .lib file first")
            return
        
        if len(self.selected_cells) < self.min_cells:
            messagebox.showwarning("Warning", f"Please select at least {self.min_cells} cells for comparison")
            return
        
        if not self.lib_parser.index1 or not self.lib_parser.index2:
            messagebox.showerror("Error", "Could not find index values in .lib file")
            return
        
        if not self._initialize_matplotlib():
            return
        
        self.ax.clear()
        
        colors = ['blue', 'red', 'green', 'orange']
        linestyles = ['-', '--', '-.', ':']
        
        for idx, sel in enumerate(self.selected_cells):
            cell_data = self.lib_parser.cells.get(sel['cell_name'])
            if not cell_data:
                continue
            
            pin_data = cell_data['pins'].get(sel['output_pin'])
            if not pin_data or not pin_data.get('timing'):
                continue
            
            arc_matrix = None
            for timing_block in pin_data['timing']:
                if sel['input_name'] in timing_block.get('related_pin', []):
                    arcs = timing_block.get('arcs', {})
                    arc_matrix = arcs.get(sel['arc_type'])
                    break
            
            if arc_matrix is None:
                continue
            
            transition_idx = self.transition_var.get()
            if transition_idx < 0 or transition_idx >= 7:
                transition_idx = 3
            
            x_values = self.lib_parser.index2
            y_values = arc_matrix[transition_idx, :]
            
            label = f"{sel['cell_name']} ({sel['arc_type']})"
            self.ax.plot(
                x_values, y_values,
                color=colors[idx % len(colors)],
                linestyle=linestyles[idx % len(linestyles)],
                linewidth=2,
                marker='o',
                markersize=4,
                label=label
            )
        
        self.ax.set_xlabel("Output Net Capacitance (fF)", fontsize=11)
        self.ax.set_ylabel("Delay/Transition Time (ns)", fontsize=11)
        self.ax.grid(True, alpha=0.3)
        self.ax.legend(loc='best', fontsize=9)
        
        transition_idx = self.transition_var.get()
        if self.lib_parser.index1 and 0 <= transition_idx < len(self.lib_parser.index1):
            transition_val = self.lib_parser.index1[transition_idx]
            title = f"Timing Arc Comparison (Input Transition = {transition_val:.3f} ns)"
        else:
            title = f"Timing Arc Comparison (Input Transition Row = {transition_idx})"
        self.ax.set_title(title, fontsize=12, fontweight='bold')
        
        self.canvas.draw()
    
    def _clear_all(self):
        """Clear all selected cells and plot."""
        self.selected_cells = []
        self._update_selected_display()
        if self.ax and self.canvas:
            self.ax.clear()
            self.ax.set_xlabel("Output Net Capacitance (fF)", fontsize=11)
            self.ax.set_ylabel("Delay/Transition Time (ns)", fontsize=11)
            self.ax.set_title("Timing Arc Comparison", fontsize=12, fontweight='bold')
            self.ax.grid(True, alpha=0.3)
            self.canvas.draw()


def main():
    """Main entry point."""
    root = tk.Tk()
    try:
        app = LibVisualizer(root)
        root.mainloop()
    except Exception as e:
        import traceback
        print("Uncaught exception in GUI:", e)
        traceback.print_exc()
        try:
            root.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    main()
