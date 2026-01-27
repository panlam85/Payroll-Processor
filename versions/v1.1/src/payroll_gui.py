#!/usr/bin/env python3
"""
Payroll Processor GUI Application

A simple drag-and-drop interface for processing payroll ZIP files.
Users can drag ZIP files containing payroll PDFs, and the application
will process them to generate employee reports.

Requirements:
    - tkinter (built-in with Python)
    - tkinterdnd2 (pip install tkinterdnd2)
    - pandas (pip install pandas)
    - xlsxwriter (pip install xlsxwriter)

Usage:
    python3 payroll_gui.py
"""

import os
import shutil
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import tempfile
from typing import List, Dict
import datetime

# Try to import tkinterdnd2 for drag-and-drop functionality
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DRAG_DROP_AVAILABLE = True
except ImportError:
    DRAG_DROP_AVAILABLE = False
    print("Warning: tkinterdnd2 not installed. Drag-and-drop will not be available.")
    print("Install with: pip install tkinterdnd2")

# Import our existing payroll processing functions
import process_payroll
import create_employee_reports
import pandas as pd


class PayrollProcessorGUI:
    """Main GUI application for payroll processing."""
    
    def __init__(self):
        """Initialize the GUI application."""
        # Create main window
        if DRAG_DROP_AVAILABLE:
            self.root = TkinterDnD.Tk()
        else:
            self.root = tk.Tk()
            
        self.root.title("Payroll Processor")
        self.root.geometry("800x600")
        self.root.minsize(600, 400)
        
        # Variables
        self.zip_files = []  # List of selected ZIP files
        self.processing = False
        self.temp_dir = None
        self.missing_dependencies = self.check_missing_dependencies()
        
        # Create GUI elements
        self.create_widgets()
        
        # Setup drag and drop if available
        if DRAG_DROP_AVAILABLE:
            self.setup_drag_drop()
        
        # Surface dependency issues immediately
        self.warn_missing_dependencies()
    
    def create_widgets(self):
        """Create and layout all GUI widgets."""
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(2, weight=1)
        
        # Title
        title_label = ttk.Label(main_frame, text="Payroll Processor", 
                               font=("Arial", 16, "bold"))
        title_label.grid(row=0, column=0, pady=(0, 20))
        
        # Instructions
        instructions = ("Drag and drop ZIP files containing payroll PDFs, "
                       "or click 'Browse' to select files.\n"
                       "Then click 'Generate Reports' to process all files.")
        if not DRAG_DROP_AVAILABLE:
            instructions = ("Click 'Browse' to select ZIP files containing payroll PDFs.\n"
                           "Then click 'Generate Reports' to process all files.")
        
        instr_label = ttk.Label(main_frame, text=instructions, 
                               justify=tk.CENTER, wraplength=600)
        instr_label.grid(row=1, column=0, pady=(0, 20))
        
        # File list frame
        list_frame = ttk.LabelFrame(main_frame, text="Selected Files", padding="5")
        list_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 20))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        
        # File listbox with scrollbar
        listbox_frame = ttk.Frame(list_frame)
        listbox_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        listbox_frame.columnconfigure(0, weight=1)
        listbox_frame.rowconfigure(0, weight=1)
        
        self.file_listbox = tk.Listbox(listbox_frame, selectmode=tk.MULTIPLE)
        self.file_listbox.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Scrollbar for listbox
        scrollbar = ttk.Scrollbar(listbox_frame, orient=tk.VERTICAL, 
                                 command=self.file_listbox.yview)
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.file_listbox.configure(yscrollcommand=scrollbar.set)
        
        # Drag and drop area (visual indicator)
        if DRAG_DROP_AVAILABLE:
            self.drop_label = ttk.Label(listbox_frame, 
                                       text="Drop ZIP files here or use Browse button",
                                       foreground="gray", anchor=tk.CENTER)
            self.drop_label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        
        # Button frame
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=3, column=0, pady=(0, 20))
        
        # Browse button
        self.browse_btn = ttk.Button(button_frame, text="Browse Files", 
                                    command=self.browse_files)
        self.browse_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        # Remove selected button
        self.remove_btn = ttk.Button(button_frame, text="Remove Selected", 
                                    command=self.remove_selected_files)
        self.remove_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        # Clear all button
        self.clear_btn = ttk.Button(button_frame, text="Clear All", 
                                   command=self.clear_all_files)
        self.clear_btn.pack(side=tk.LEFT, padx=(0, 20))
        
        # Generate reports button
        self.generate_btn = ttk.Button(button_frame, text="Generate Reports", 
                                      command=self.generate_reports, 
                                      style="Accent.TButton")
        self.generate_btn.pack(side=tk.LEFT)
        
        # Progress frame
        progress_frame = ttk.Frame(main_frame)
        progress_frame.grid(row=4, column=0, sticky=(tk.W, tk.E))
        progress_frame.columnconfigure(0, weight=1)
        
        # Progress bar
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, 
                                           maximum=100)
        self.progress_bar.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 5))
        
        # Status label
        self.status_var = tk.StringVar()
        self.status_var.set("Ready")
        self.status_label = ttk.Label(progress_frame, textvariable=self.status_var)
        self.status_label.grid(row=1, column=0)
        
        # Update button states
        self.update_ui_state()
    
    def check_missing_dependencies(self) -> List[str]:
        """Return a list of missing external dependencies."""
        missing = []
        if shutil.which("pdftotext") is None:
            missing.append("pdftotext (install with 'brew install poppler')")
        return missing
    
    def warn_missing_dependencies(self):
        """Show a non-blocking warning if dependencies are missing."""
        if getattr(self, "status_var", None) and self.missing_dependencies:
            warning = "Missing dependencies: " + ", ".join(self.missing_dependencies)
            self.status_var.set(warning)
    
    def ensure_dependencies_available(self) -> bool:
        """Ensure required tools are installed before processing."""
        self.missing_dependencies = self.check_missing_dependencies()
        if self.missing_dependencies:
            warning = "\n".join(f"• {item}" for item in self.missing_dependencies)
            messagebox.showerror(
                "Missing Dependencies",
                "Payroll Processor needs the following tools:\n\n"
                f"{warning}\n\nInstall them and try again."
            )
            self.warn_missing_dependencies()
            return False
        return True
    
    def setup_drag_drop(self):
        """Setup drag and drop functionality."""
        if not DRAG_DROP_AVAILABLE:
            return
            
        # Enable drag and drop on the file listbox
        self.file_listbox.drop_target_register(DND_FILES)
        self.file_listbox.dnd_bind('<<Drop>>', self.on_drop)
    
    def on_drop(self, event):
        """Handle dropped files."""
        if self.processing:
            return
            
        files = self.root.tk.splitlist(event.data)
        zip_files = [f for f in files if f.lower().endswith('.zip')]
        
        if not zip_files:
            messagebox.showwarning("Invalid Files", 
                                 "Please drop only ZIP files containing payroll data.")
            return
        
        # Add files to list
        for zip_file in zip_files:
            if zip_file not in self.zip_files:
                self.zip_files.append(zip_file)
        
        self.update_file_list()
        self.update_ui_state()
    
    def browse_files(self):
        """Open file browser to select ZIP files."""
        print("DEBUG: browse_files() called")  # Debug print
        if self.processing:
            print("DEBUG: browse_files() - currently processing, returning")  # Debug print
            return
            
        files = filedialog.askopenfilenames(
            title="Select Payroll ZIP Files",
            filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")]
        )
        
        print(f"DEBUG: Selected files: {files}")  # Debug print
        
        # Add selected files
        for file_path in files:
            if file_path not in self.zip_files:
                self.zip_files.append(file_path)
                print(f"DEBUG: Added file: {file_path}")  # Debug print
        
        print(f"DEBUG: zip_files after adding: {self.zip_files}")  # Debug print
        self.update_file_list()
        self.update_ui_state()
    
    def remove_selected_files(self):
        """Remove selected files from the list."""
        if self.processing:
            return
            
        selected_indices = self.file_listbox.curselection()
        if not selected_indices:
            messagebox.showinfo("No Selection", "Please select files to remove.")
            return
        
        # Remove files in reverse order to maintain indices
        for index in reversed(selected_indices):
            del self.zip_files[index]
        
        self.update_file_list()
        self.update_ui_state()
    
    def clear_all_files(self):
        """Clear all files from the list."""
        if self.processing:
            return
            
        if self.zip_files:
            if messagebox.askyesno("Clear All", "Remove all files from the list?"):
                self.zip_files.clear()
                self.update_file_list()
                self.update_ui_state()
    
    def update_file_list(self):
        """Update the file listbox display."""
        self.file_listbox.delete(0, tk.END)
        for zip_file in self.zip_files:
            filename = os.path.basename(zip_file)
            self.file_listbox.insert(tk.END, filename)
        
        # Hide/show drop label
        if DRAG_DROP_AVAILABLE:
            if self.zip_files:
                self.drop_label.place_forget()
            else:
                self.drop_label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
    
    def update_ui_state(self):
        """Update button states based on current state."""
        has_files = bool(self.zip_files)
        print(f"DEBUG: update_ui_state - has_files={has_files}, processing={self.processing}")  # Debug print
        print(f"DEBUG: zip_files content: {self.zip_files}")  # Debug print
        deps_ready = not self.missing_dependencies
        
        # Enable/disable buttons based on state
        state = tk.DISABLED if self.processing else tk.NORMAL
        generate_state = state if has_files else tk.DISABLED
        print(f"DEBUG: generate_btn state will be: {generate_state}")  # Debug print
        
        self.browse_btn.configure(state=state)
        self.remove_btn.configure(state=state if has_files else tk.DISABLED)
        self.clear_btn.configure(state=state if has_files else tk.DISABLED)
        self.generate_btn.configure(state=generate_state)
        
        if not deps_ready:
            self.warn_missing_dependencies()
    
    def generate_reports(self):
        """Generate payroll reports from selected files."""
        print("DEBUG: generate_reports() called")  # Debug print
        print(f"DEBUG: zip_files = {self.zip_files}")  # Debug print
        print(f"DEBUG: processing = {self.processing}")  # Debug print
        
        if not self.zip_files:
            print("DEBUG: No zip files found")  # Debug print
            messagebox.showwarning("No Files", "Please select ZIP files first.")
            return
        
        if not self.ensure_dependencies_available():
            return
        
        if self.processing:
            print("DEBUG: Already processing")  # Debug print
            return
        
        # Ask user for output location
        output_file = filedialog.asksaveasfilename(
            title="Save Employee Reports As",
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
            initialname=f"employee_reports_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        )
        
        if not output_file:
            return
        
        # Start processing in a separate thread
        self.processing = True
        self.update_ui_state()
        
        thread = threading.Thread(target=self.process_files, args=(output_file,))
        thread.daemon = True
        thread.start()
    
    def process_files(self, output_file):
        """Process the ZIP files and generate reports."""
        try:
            self.update_status("Initializing...")
            self.update_progress(0)
            
            # Create temporary directory
            with tempfile.TemporaryDirectory() as temp_dir:
                self.temp_dir = temp_dir
                csv_files = []
                
                total_files = len(self.zip_files)
                
                # Process each ZIP file
                for i, zip_file in enumerate(self.zip_files):
                    self.update_status(f"Processing {os.path.basename(zip_file)}...")
                    progress = (i / total_files) * 80  # Use 80% for processing
                    self.update_progress(progress)
                    
                    try:
                        # Process the ZIP file
                        df = process_payroll.process_zip(zip_file, temp_dir)
                        
                        if not df.empty:
                            # Save to temporary CSV
                            csv_path = os.path.join(temp_dir, f"temp_payroll_{i}.csv")
                            df["SourceArchive"] = os.path.basename(zip_file)
                            
                            # Normalize numeric fields
                            numeric_cols = [
                                "BasicSalary", "TotalEarnings", "NetPay",
                                "EFKAEmployee", "EFKAEmployer", "TEKAEmployee", "TEKAEmployer"
                            ]
                            for col in numeric_cols:
                                if col in df.columns:
                                    df[col] = df[col].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
                                    df[col] = pd.to_numeric(df[col], errors='coerce')
                            
                            df.to_csv(csv_path, index=False)
                            csv_files.append(csv_path)
                        
                    except Exception as e:
                        self.update_status(f"Error processing {os.path.basename(zip_file)}: {str(e)}")
                        continue
                
                if not csv_files:
                    self.update_status("No payroll data found in any files.")
                    messagebox.showerror("No Data", "No payroll data could be extracted from the selected files.")
                    return
                
                # Generate employee reports
                self.update_status("Generating employee reports...")
                self.update_progress(85)
                
                # Load and combine all CSV data
                combined_df = create_employee_reports.load_payroll_data(csv_files)
                
                if combined_df.empty:
                    self.update_status("No data to process.")
                    messagebox.showerror("No Data", "No valid payroll data found.")
                    return
                
                # Prepare summary
                self.update_progress(90)
                summary_df = create_employee_reports.prepare_summary(combined_df)
                
                # Write Excel reports
                self.update_progress(95)
                create_employee_reports.write_employee_reports(summary_df, output_file)
                
                # Complete
                self.update_progress(100)
                self.update_status(f"Reports generated successfully!")
                
                # Show success message
                num_employees = len(summary_df['EmployeeCode'].unique()) if not summary_df.empty else 0
                num_records = len(combined_df)
                
                messagebox.showinfo("Success", 
                                   f"Employee reports generated successfully!\n\n"
                                   f"• Processed {total_files} ZIP files\n"
                                   f"• Found {num_records} payroll records\n"
                                   f"• Created reports for {num_employees} employees\n"
                                   f"• Saved to: {output_file}")
                
        except Exception as e:
            self.update_status(f"Error: {str(e)}")
            messagebox.showerror("Error", f"An error occurred while processing:\n\n{str(e)}")
        
        finally:
            self.processing = False
            self.root.after(0, self.update_ui_state)
            if not self.processing:
                self.root.after(2000, lambda: self.update_status("Ready"))
    
    def update_status(self, message):
        """Update status label thread-safely."""
        self.root.after(0, lambda: self.status_var.set(message))
    
    def update_progress(self, value):
        """Update progress bar thread-safely."""
        self.root.after(0, lambda: self.progress_var.set(value))
    
    def run(self):
        """Start the GUI application."""
        self.root.mainloop()


def main():
    """Main entry point."""
    app = PayrollProcessorGUI()
    app.run()


if __name__ == "__main__":
    main()
