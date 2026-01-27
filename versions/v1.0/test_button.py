#!/usr/bin/env python3
"""Simple test to verify button functionality."""

import tkinter as tk
from tkinter import ttk, messagebox
import os
import sys

def test_button():
    """Test function for button click."""
    print("Button clicked successfully!")
    messagebox.showinfo("Test", "Button is working!")

def main():
    """Create simple test GUI."""
    root = tk.Tk()
    root.title("Button Test")
    root.geometry("300x200")
    
    # Add some files to simulate selection
    test_files = []
    
    # Create a simple file list
    frame = ttk.Frame(root)
    frame.pack(expand=True, fill='both', padx=20, pady=20)
    
    # File listbox
    listbox = tk.Listbox(frame)
    listbox.pack(expand=True, fill='both', pady=(0, 10))
    
    # Add test file
    test_file = "/Users/tiktaknto/Desktop/payment processor/01 4106102025.zip"
    if os.path.exists(test_file):
        listbox.insert(tk.END, os.path.basename(test_file))
        test_files.append(test_file)
        print(f"Added test file: {test_file}")
    else:
        listbox.insert(tk.END, "No test file found")
        print("Test file not found")
    
    # Test button
    def button_click():
        print("Button clicked - this should print")
        if test_files:
            messagebox.showinfo("Success", f"Would process {len(test_files)} file(s)")
        else:
            messagebox.showwarning("No Files", "No files to process")
    
    btn = ttk.Button(frame, text="Test Generate Reports", command=button_click)
    btn.pack()
    
    root.mainloop()

if __name__ == "__main__":
    main()