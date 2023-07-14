import Rectangulator
import Loginulator
import win32print
import threading
import traceback
import win32api
import imaplib
import smtplib
import config
import email
import time
import os
import tkinter as tk
from Alertinator import AlertWindow
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

class EmailProcessor:

    # CONSTANTS
    LOG_FILE = config.LOG_FILE
    TEMPLATE_FOLDER = config.TEMPLATE_FOLDER
    INVOICE_FOLDER = config.INVOICE_FOLDER
    ACP_USER, ACP_PASS = config.ACP_USER, config.ACP_PASS
    APC_USER, APC_PASS = config.APC_USER, config.APC_PASS
    IMAP_SERVER = config.IMAP_SERVER
    SMTP_SERVER = config.SMTP_SERVER
    RECIEVER_EMAIL = config.RECIEVER_EMAIL
    TRUSTED_ADDRESS = config.TRUSTED_ADDRESS
    ADDRESS = config.ADDRESS
    WAIT_TIME = 10 # seconds
    RECONNECT_TIME = 3600 # 1 hour
    RECONNECT_CYCLE_COUNT = RECONNECT_TIME // WAIT_TIME

    def __init__(self, root):
        # VARIABLES
        self.alert_window = None # used for pop ups
        self.window_closed = None
        self.processor_thread = None
        self.processor_running = False
        self.pause_event = threading.Event() # used for cycles
        self.root = root
        self.connected = False
        self.logging_out = False
        self.TESTING = False # default to false

        # GUI BUTTONS
        self.button_frame = tk.Frame(root)
        self.button_frame.pack(side=tk.TOP)

        self.start_button = tk.Button(self.button_frame, text="Start Process", command=self.main) # start process button
        self.start_button.pack(side=tk.LEFT, padx=1)

        self.pause_button = tk.Button(self.button_frame, text="Pause", command=self.pause_processing, state=tk.DISABLED) # pause button
        self.pause_button.pack(side=tk.LEFT, padx=1)

        self.logout_button = tk.Button(self.button_frame, text="Logout", command=self.logout, state=tk.DISABLED) # logout button
        self.logout_button.pack(side=tk.LEFT, padx=1)

        self.errors_button = tk.Button(self.button_frame, text="Resolve Errors", command=self.resolve_errors, state=tk.DISABLED) # move errors to inbox
        self.errors_button.pack(side=tk.LEFT, padx=1)

        self.testing_button = tk.Button(self.button_frame, text="Testing", command=self.toggle_testing, state=tk.NORMAL, bg="#FFCCCC", fg="black") # testing button
        self.testing_button.pack(side=tk.LEFT, padx=1)

        scrollbar = tk.Scrollbar(root)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.log_text_widget = tk.Text(root, yscrollcommand=scrollbar.set, height=30, width=140, spacing1=4, padx=0, pady=0) # text label
        self.log_text_widget.pack(side=tk.LEFT, fill=tk.BOTH)
        scrollbar.configure(command=self.log_text_widget.yview)

        # GUI STYLES
        self.log_text_widget.tag_configure("red", background="#FFCCCC")
        self.log_text_widget.tag_configure("yellow", background="yellow")
        self.log_text_widget.tag_configure("orange", background="#FFB434")	
        self.log_text_widget.tag_configure("lgreen", background="#CCFFCC") # light green
        self.log_text_widget.tag_configure("green", background="#39FF12") # green
        self.log_text_widget.tag_configure("dgreen", background="#00994d") # dark green
        self.log_text_widget.tag_configure("blue", background="#89CFF0")
        self.log_text_widget.tag_configure("purple", background="#E6E6FA")
        self.log_text_widget.tag_configure("gray", background="#DEDDDD")
        self.log_text_widget.tag_configure("no_new_emails", background="#DEDDDD") # gray
        self.log_text_widget.tag_configure("default", borderwidth=0.5, relief="solid", lmargin1=10, offset=8) # default

        self.root.protocol("WM_DELETE_WINDOW", self.on_program_exit) # runs exit protocol on window close
        

    def main(self): # Runs when start button is pressed 
        if self.TESTING:
            self.TEMPLATE_FOLDER = config.TEST_TEMPLATE_FOLDER
            self.INVOICE_FOLDER = config.TEST_INVOICE_FOLDER
            self.log("Testing mode enabled", tag="orange")

        self.log("Connecting...", tag="dgreen")
        self.root.update()
        self.processor_running = True

        # Enable and disable buttons
        self.start_button.config(state=tk.DISABLED) 
        self.pause_button.config(text="Pause", command=self.pause_processing, state=tk.NORMAL)
        self.pause_event.clear()
        self.logout_button.config(state=tk.NORMAL)
        self.testing_button.config(state=tk.DISABLED)
        self.errors_button.config(state=tk.NORMAL)
        
        # ACP login
        self.imap_acp = self.connect(self.ACP_USER, self.ACP_PASS)
        if self.imap_acp:
            self.processor_thread = threading.Thread(target=self.search_inbox, args=[self.imap_acp])
            self.processor_thread.start()

        # APC login
        self.imap_apc = self.connect(self.APC_USER, self.APC_PASS)
        if self.imap_apc:
            self.processor_thread = threading.Thread(target=self.search_inbox, args=[self.imap_apc])
            self.processor_thread.start()


    def connect(self, username, password, log=True): # returns imap object
        user = f"{username}{self.ADDRESS}"
        try:
            # Login to email
            imap = imaplib.IMAP4_SSL(self.IMAP_SERVER)
            imap.login(user, password)
            self.connected = True
            if log:
                self.log(f"--- Connected to {username} --- {self.current_time} {self.current_date}", tag="dgreen")
            return MYImap(imap, username, password)
        except imaplib.IMAP4_SSL.error as e:
            if log:
                self.log(f"Unable to connect to {username}: {str(e)}", tag="red", sender_imap=imap)
            time.sleep(5)
            return self.connect(username, password, log=False) # try again after 5 seconds
        

    def disconnect(self, imap, log=True):
        try:
            # Logout
            imap.imap.logout()
            self.connected = False
            if log:
                self.log(f"--- Disconnected from {imap.username} --- {self.current_time} {self.current_date}", tag="red")
        except Exception as e:
            if log:
                self.log(f"An error occurred while disconnecting: {str(e)}", tag="red", sender_imap=imap)    
            time.sleep(5)    
            self.disconnect(imap, log=False) # try again after 5 seconds


    def search_inbox(self, imap): # Main Loop - searches inbox for new emails
        try:
            cycle_count = 0
            while imap.processor_running and self.processor_running:
                if not self.pause_event.is_set() and self.connected:
                    # Search for all emails in the inbox
                    imap.imap.select("inbox")
                    _, emails = imap.imap.search(None, "ALL")

                    # Check if no new mail
                    if not emails[0]:
                        self.log(f"No new emails for {imap.username} - {self.current_time} {self.current_date}", tag="no_new_emails")

                        # Check if emails need to be looked at every 3 cycles
                        if cycle_count % 3 == 0:
                            self.check_labels(imap, ["Need_Print", "Need_Login", "Errors"])

                        # Pause until next cycle
                        self.pause_event.wait(timeout=self.WAIT_TIME)
                    else:
                        self.process_email(imap, emails[0].split()[0])

                    cycle_count += 1
                    # Reconnect every hour
                    if cycle_count == self.RECONNECT_CYCLE_COUNT:
                        imap = self.reconnect(imap)
                        cycle_count = 0
                        
            # Disconnect when the program is closed
            self.disconnect(imap)
            if self.logging_out:
                self.logging_out = False
                self.start_button.config(state=tk.NORMAL)
                self.testing_button.config(state=tk.NORMAL)
        except Exception as e:  
            self.log(f"An error occurred while searching the inbox for {imap.username}: {str(e)}", tag="red", sender_imap=imap)
            self.restart_processing(imap)


    def process_email(self, imap, mail): # Handles each email
        subject = ""
        try: 
            # Fetch email
            _, data = imap.imap.fetch(mail, "(RFC822)")
            raw_email = data[0][1]
            msg = email.message_from_bytes(raw_email)
            subject = msg["Subject"]
            sender_email = email.utils.parseaddr(msg["From"])[1]

            # Check if sender is trusted
            if not sender_email.endswith(self.TRUSTED_ADDRESS):
                self.move_email(imap, mail, "Not_Invoices")
                return
            
            # Check for attachments
            has_attachment = any(part.get("content-disposition", "").startswith("attachment") for part in msg.walk() if msg.is_multipart())
            if not has_attachment:
                attachment_error = self.handle_login(imap, mail, msg, subject)
            else:            
                # Handle attachments
                attachment_error = self.handle_attachments(imap, mail, msg, subject)

            # Move to invoices label if no errors
            if not attachment_error:
                self.move_email(imap, mail, "Invoices")
            else:
                self.log(f"'{subject}' failed to download, moved to Error label for {imap.username}", tag="red", sender_imap=imap)
                self.move_email(imap, mail, "Errors")

        except Exception as e:
            self.log(f"An error occurred while processing an email for {imap.username}: {str(e)} \n {traceback.format_exc()}", tag="red", sender_imap=imap)
            self.move_email(imap, mail, "Errors")
            return
        

    def handle_login(self, imap, mail, msg, subject): # Handles login emails
        filepaths = Loginulator.get_filepaths(msg)
        if not filepaths:
            self.log(f"Loginulator failed for '{subject}' for {imap.username}", tag="red", sender_imap=imap)
            self.move_email(imap, mail, "Need_Login")
            return True
        
        for filepath in filepaths:
            new_filepath = Rectangulator.main(filepath, self, self.TEMPLATE_FOLDER)
            try:
                # Save invoice
                os.rename(filepath, new_filepath)
                self.log(f"Created new invoice file {os.path.basename(new_filepath)} for {imap.username}", tag="blue")
                self.print_invoice(new_filepath, imap, mail, subject)
                return False
            except Exception as e:
                self.log(f"An error occurred while renaming {filepath} to {new_filepath}: {str(e)}", tag="red", sender_imap=imap)
                return True


    def handle_attachments(self, imap, mail, msg, subject):        # Iterate over email parts and find pdf
        error = False
        for part in msg.walk():
            if part.get_content_disposition() is not None and part.get_filename() is not None and part.get_filename().lower().endswith(".pdf"):
                # Check if download is successful
                invoice_downloaded, filepath = self.download_invoice(part, imap)
                if invoice_downloaded == "not_invoice":
                    continue
                elif not invoice_downloaded:
                    error = True
                    continue
            
                if not self.TESTING:
                    self.print_invoice(filepath, imap, mail, subject)
        return error


    def download_invoice(self, part, imap):
        # Get fllename and attachment
        filename = part.get_filename()
        attachment = part.get_payload(decode=True)
        
        filepath = os.path.join(self.INVOICE_FOLDER, filename)
        
        # Check if file already exists
        if os.path.exists(filepath):
            self.log(f"Invoice file already exists at {filepath} for {imap.username}", tag="red", sender_imap=imap)
            return False, None

        # Download invoice PDF
        with open(filepath, 'wb') as file:
            file.write(attachment)

        # Prompt user to draw rectangles
        new_filepath = Rectangulator.main(filepath, self, self.TEMPLATE_FOLDER)

        # Check if not invoice
        if new_filepath == "not_invoice":
            os.remove(filepath)
            return "not_invoice", None

        # Check if Rectangulator fails
        if new_filepath == None:
            self.log(f"Rectangulator failed for {imap.username}", tag="red", sender_imap=imap)
            os.remove(filepath)
            return False, None
        
        # Check if invoice has already been processed
        if os.path.exists(new_filepath):
            os.remove(filepath)
            self.log(f"New invoice file already exists at {new_filepath} for {imap.username}", tag="red", sender_imap=imap)
            return False, None
        
        # Save invoice
        os.rename(filepath, new_filepath)
        self.log(f"Created new invoice file {os.path.basename(new_filepath)} for {imap.username} - {self.current_date} {self.current_time}", tag="blue")
        return True, new_filepath
        

    def print_invoice(self, filepath, imap, mail, subject): # Printer
        try:
            # Get default printer and print
            p = win32print.GetDefaultPrinter()
            win32api.ShellExecute(0, "print", filepath, None,  ".",  0)
            self.log(f"Printed {os.path.basename(filepath)} completed successfully for {imap.username}.", tag="blue")
            return True
        except Exception as e:
            self.move_email(imap, mail, "Need_Print")
            self.log(f"Printing failed: {str(e)}", tag="red", sender_imap=imap)
            return False


    def move_email(self, imap, mail, label): # Moves emails to labels
        subject = "Unknown"
        try:
            # Get email subject
            _, data = imap.imap.fetch(mail, "(RFC822)")
            raw_email = data[0][1]
            msg = email.message_from_bytes(raw_email)
            subject = msg["Subject"]

            # Make a copy of the email in the specified label
            copy = imap.imap.copy(mail, label)

            # Mark the original email as deleted
            imap.imap.store(mail, '+FLAGS', '\\Deleted')
            imap.imap.expunge()
            self.log(f"Email '{subject}' moved to {label} for {imap.username}.", tag="blue")
        except Exception as e:
            self.log(f"Email '{subject}' transfer failed for {imap.username}: {str(e)}", tag="red", sender_imap=imap)


    def send_email(self, imap, subject, body):
        try:
            if self.TESTING:
                return 
            
            sender_email = f"{imap.username}{self.ADDRESS}"

            # Create a multipart message and set headers
            message = MIMEMultipart()
            message["Subject"] = subject
            message["From"] = sender_email
            message["To"] = self.RECIEVER_EMAIL
            message.attach(MIMEText(body, "plain"))

            # Send the email using SMTP
            with smtplib.SMTP(self.SMTP_SERVER, 587) as server:
                server.starttls()
                server.login(sender_email, imap.password)
                server.sendmail(sender_email, self.RECIEVER_EMAIL, message.as_string())
                self.log(f"Email from {imap.username} sent to {self.RECIEVER_EMAIL}", tag="gray")
        except Exception as e:
                self.log(f"Error sending email from {imap.username} - {str(e)}", tag="red")


    def log(self, *args, tag=None, sender_imap=None): # Logs to text box and log file
        try:
            if self.window_closed: #check if window is still open
                return
            message = ' '.join([str(arg) for arg in args]) #convert args to string

            # Get rid of no_new_emails messages
            if tag == "no_new_emails":
                self.remove_messages(message)
            
            # Insert the new message to the text widget
            self.log_text_widget.insert(tk.END, message + "\n", (tag, "default"))
            # If the bottom quarter of the text widget is visible, autoscroll
            if self.log_text_widget.yview()[1] > 0.75:
                self.log_text_widget.yview_moveto(1)

            # Send email for errors
            if tag == "red" and sender_imap:
                self.send_email(sender_imap, "Error Alert", message)
            
            # Write to the log file
            with open(self.LOG_FILE, "a") as file:
                file.write(message + "\n")
        except Exception as e:
            print(f"Error logging: {str(e)}")


    def check_labels(self, imap, labels): # Checks for emails that need to be looked at in labels
        for label in labels:
            try:
                # Check if any emails in specified label
                imap.imap.select(label)
                _, data = imap.imap.search(None, 'ALL')
                email_ids = data[0].split()

                # Alert user if there are emails
                if len(email_ids) > 0:
                    self.log(f"{len(email_ids)} emails in {label} for {imap.username} - {self.current_time} {self.current_date}", tag="orange")
            except Exception as e:
                self.log(f"An error occurred while checking the label for {imap.username}: {str(e)}", tag="red", sender_imap=imap)
    

    def remove_messages(self, message): # Removes no_new_emails messages
        message = message[:-22] #cuts out the date-time

        # Searches for every no_new_emails message then deletes it
        index = self.log_text_widget.search(message, "1.0", tk.END)
        while index:
            self.log_text_widget.delete(index, f"{index}+{len(message)+1+22}c") #+1 for new line, +22 for date-time
            index = self.log_text_widget.search(message, "1.0", tk.END)
            self.root.update()


    def resolve_errors(self): # Moves error emails back to inbox
        try:
            self.log(f"Attempting to resolve errors.", tag="blue")
            for imap in [self.imap_acp, self.imap_apc]:
                # Get emails in error label
                imap.imap.select("Errors")
                _, data = imap.imap.search(None, 'ALL')
                email_ids = data[0].split()

                if len(email_ids) == 0:
                    self.log(f"No errors to resolve for {imap.username}.", tag="blue")
                    continue

                # Move emails back to inbox
                for email_id in email_ids:
                    self.move_email(imap, email_id, "inbox")
        except Exception as e:
            self.log(f"Error resolving errors for {imap.username}: {str(e)}", tag="red", sender_imap=imap)


    def pause_processing(self): # Pauses processing
        self.log("Processing paused.", tag="yellow")
        self.pause_button.config(text="Resume", command=self.resume_processing)
        self.errors_button.config(state=tk.DISABLED)
        self.pause_event.set()


    def resume_processing(self): # Resumes processing
        self.log("Processing resumed.", tag="yellow")
        self.pause_button.config(text="Pause", command=self.pause_processing)
        self.errors_button.config(state=tk.NORMAL)
        self.pause_event.clear()

 
    def restart_processing(self, imap): # Restarts processing
        self.log(f"Restarting {imap.username}", tag="orange")
        self.disconnect(imap)
        imap = self.connect(imap.username, imap.password)

   
    def logout(self): # Logs out
        self.log("Logging out...", tag="orange")
        self.pause_button.config(state=tk.DISABLED)
        self.errors_button.config(state=tk.DISABLED)
        self.logout_button.config(state=tk.DISABLED)
        self.pause_event.set()
        self.processor_running = False
        self.logging_out = True

   
    def toggle_testing(self):
        if self.TESTING:
            self.TESTING = False
            self.testing_button.config(bg="#FFCCCC")
        else:
            self.TESTING = True
            self.testing_button.config(bg="#CCFFCC")


    def reconnect(self, imap): # Reconnects to imap
        self.disconnect(imap, log=False)
        imap = self.connect(imap.username, imap.password, log=False)
        self.log(f"Reconnected to {imap.username} - {self.current_time} {self.current_date}", tag="green")
        return imap


    def on_program_exit(self): # Runs when program is closed
        self.log("Disconnecting...", tag="red")
        self.root.update()
        self.window_closed = True

        # Close alert windows
        if self.alert_window:
            self.alert_window.destroy() 

        # Disconnect imaps if running
        if self.processor_thread:
            self.processor_running = False  #set the flag to stop the email processing loop
            self.pause_event.set()
            self.processor_thread.join()

        # Destroys tkinter window 
        self.root.destroy()


    @property
    def current_time(self):
        return time.strftime("%H:%M:%S", time.localtime())
    

    @property
    def current_date(self):
        return time.strftime("%Y-%m-%d", time.localtime())

class MYImap:
    
    def __init__(self, imap, username, password):
        self.imap = imap
        self.username = username
        self.password = password
        self.processor_running = True
    

if __name__ == "__main__":
    # Setup gui
    icon_path = os.path.join(os.path.dirname(__file__), "hotpot.ico")   
    root = tk.Tk()
    root.title("Pewter")
    root.iconbitmap(icon_path)
    root.geometry("1200x600")
    email_processor = EmailProcessor(root)
    root.mainloop()