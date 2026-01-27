#!/usr/bin/env python3
"""
Fixed Payroll Processor GUI Application

A simple interface for processing payroll ZIP files with debugging.
"""

import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import tempfile
from typing import List
import datetime

# Import our existing payroll processing functions
try:
    import process_payroll
    import create_employee_reports
    import pandas as pd
    MODULES_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import required modules: {e}")
    MODULES_AVAILABLE = False


class PayrollProcessorGUI:
    """Main GUI application for payroll processing."""
    
    def __init__(self):
        """Initialize the GUI application."""
        # Create main window
        self.root = tk.Tk()
        self.root.title("Greek Payroll Processor")
        self.root.geometry("600x400")
        
        # Initialize state
        self.zip_files = []
        self.processing = False
        
        # Create GUI elements
        self.create_widgets()
        
        # Initialize UI state
        self.update_ui_state()
    
    def create_widgets(self):
        """Create and arrange GUI widgets."""
        # Main frame
        main_frame = ttk.Frame(self.root)
        main_frame.pack(expand=True, fill='both', padx=20, pady=20)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(2, weight=1)
        
        # Title
        title_label = ttk.Label(main_frame, text="Greek Payroll Processor", 
                               font=('Arial', 16, 'bold'))
        title_label.grid(row=0, column=0, pady=(0, 20))
        
        # Instructions
        instructions = ("Select ZIP files containing payroll PDFs.\n"
                       "The application will extract employee data and generate Excel reports.")
        instructions_label = ttk.Label(main_frame, text=instructions, 
                                     font=('Arial', 10), justify=tk.CENTER)
        instructions_label.grid(row=1, column=0, pady=(0, 20))
        
        # File list frame
        list_frame = ttk.LabelFrame(main_frame, text="Selected Files", padding=10)
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
                                      command=self.generate_reports)
        self.generate_btn.pack(side=tk.LEFT)
        
        # Progress frame
        progress_frame = ttk.Frame(main_frame)
        progress_frame.grid(row=4, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        progress_frame.columnconfigure(0, weight=1)
        
        # Progress bar
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, 
                                          maximum=100)
        self.progress_bar.grid(row=0, column=0, sticky=(tk.W, tk.E))
        
        # Status label
        self.status_var = tk.StringVar(value="Ready")
        self.status_label = ttk.Label(main_frame, textvariable=self.status_var)
        self.status_label.grid(row=5, column=0)
    
    def browse_files(self):
        """Open file browser to select ZIP files."""
        print("DEBUG: browse_files() called")
        if self.processing:
            print("DEBUG: Currently processing, ignoring browse request")
            return
            
        files = filedialog.askopenfilenames(
            title="Select Payroll ZIP Files",
            filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")]
        )
        
        print(f"DEBUG: User selected files: {files}")
        
        # Add selected files
        for file_path in files:
            if file_path not in self.zip_files:
                self.zip_files.append(file_path)
                print(f"DEBUG: Added file to list: {file_path}")
        
        print(f"DEBUG: Current zip_files list: {self.zip_files}")
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
        print("DEBUG: Updating file list display")
        self.file_listbox.delete(0, tk.END)
        for zip_file in self.zip_files:
            filename = os.path.basename(zip_file)
            self.file_listbox.insert(tk.END, filename)
            print(f"DEBUG: Added to listbox: {filename}")
    
    def update_ui_state(self):
        """Update button states based on current state."""
        has_files = bool(self.zip_files)
        print(f"DEBUG: update_ui_state - has_files={has_files}, processing={self.processing}")
        
        # Enable/disable buttons based on state
        state = tk.DISABLED if self.processing else tk.NORMAL
        
        self.browse_btn.configure(state=state)
        self.remove_btn.configure(state=state if has_files else tk.DISABLED)
        self.clear_btn.configure(state=state if has_files else tk.DISABLED)
        self.generate_btn.configure(state=state)  # Always enabled when not processing
        
        print(f"DEBUG: Buttons - browse:{state}, generate:{state}, has_files:{has_files}")
    
    def generate_reports(self):
        """Generate payroll reports from selected files."""
        print("DEBUG: generate_reports() called!")
        print(f"DEBUG: zip_files = {self.zip_files}")
        print(f"DEBUG: processing = {self.processing}")
        print(f"DEBUG: MODULES_AVAILABLE = {MODULES_AVAILABLE}")
        
        if not MODULES_AVAILABLE:
            messagebox.showerror("Missing Modules", 
                               "Required modules (process_payroll, create_employee_reports) not available.")
            return
        
        if not self.zip_files:
            print("DEBUG: No zip files found")
            messagebox.showwarning("No Files", "Please select ZIP files first.")
            return
        
        if self.processing:
            print("DEBUG: Already processing")
            return
        
        # Test with a simple message first
        result = messagebox.askyesno("Confirm Processing", 
                                   f"Process {len(self.zip_files)} ZIP file(s)?\\n\\n" +
                                   "\\n".join([os.path.basename(f) for f in self.zip_files]))
        
        if not result:
            print("DEBUG: User cancelled processing")
            return
        
        # Ask user for output location
        output_file = filedialog.asksaveasfilename(
            title="Save Employee Reports As",
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
            initialname=f"employee_reports_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        )
        
        if not output_file:
            print("DEBUG: No output file selected")
            return
        
        print(f"DEBUG: Starting processing with output file: {output_file}")
        
        # Start processing in a separate thread
        self.processing = True
        self.update_ui_state()
        
        thread = threading.Thread(target=self.process_files, args=(output_file,))
        thread.daemon = True
        thread.start()
    
    def process_files(self, output_file):
        """Process the ZIP files and generate reports."""
        try:
            print("DEBUG: process_files() started")
            self.update_status("Initializing...")
            self.update_progress(0)
            
            # Create temporary directory
            with tempfile.TemporaryDirectory() as temp_dir:
                self.temp_dir = temp_dir
                csv_files = []
                
                total_files = len(self.zip_files)
                print(f"DEBUG: Processing {total_files} files")
                
                # Process each ZIP file
                for i, zip_file in enumerate(self.zip_files):
                    self.update_status(f"Processing {os.path.basename(zip_file)}...")
                    progress = (i / total_files) * 80  # Use 80% for processing
                    self.update_progress(progress)
                    
                    try:
                        print(f"DEBUG: Processing file {i+1}/{total_files}: {zip_file}")
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
                            print(f"DEBUG: Successfully processed and saved to {csv_path}")
                        else:
                            print(f"DEBUG: No data extracted from {zip_file}")
                        
                    except Exception as e:
                        print(f"DEBUG: Error processing {zip_file}: {str(e)}")
                        self.update_status(f"Error processing {os.path.basename(zip_file)}: {str(e)}")
                        continue
                
                if not csv_files:
                    print("DEBUG: No CSV files created")
                    self.update_status("No payroll data found in any files.")
                    messagebox.showerror("No Data", "No payroll data could be extracted from the selected files.")
                    return
                
                # Generate employee reports
                print("DEBUG: Generating employee reports")
                self.update_status("Generating employee reports...")
                self.update_progress(85)
                
                # Load and combine all CSV data
                combined_df = create_employee_reports.load_payroll_data(csv_files)
                
                if combined_df.empty:
                    print("DEBUG: Combined dataframe is empty")
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
                
                print(f"DEBUG: Success! {num_records} records, {num_employees} employees")
                
                messagebox.showinfo("Success", 
                                   f"Employee reports generated successfully!\\n\\n"
                                   f"• Processed {total_files} ZIP files\\n"
                                   f"• Found {num_records} payroll records\\n"
                                   f"• Created reports for {num_employees} employees\\n"
                                   f"• Saved to: {output_file}")
                
        except Exception as e:
            print(f"DEBUG: Exception in process_files: {str(e)}")
            self.update_status(f"Error: {str(e)}")
            messagebox.showerror("Error", f"An error occurred while processing:\\n\\n{str(e)}")
        
        finally:
            print("DEBUG: process_files() finished")
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
    print("DEBUG: Starting Payroll Processor GUI")
    app = PayrollProcessorGUI()
    app.run()


if __name__ == "__main__":
    main()