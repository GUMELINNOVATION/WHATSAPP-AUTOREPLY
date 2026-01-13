# whatsapp_auto_reply_app.py
"""
WhatsApp Auto-Reply Desktop Application
Cross-platform GUI app for auto-replying to WhatsApp messages
"""

import time
import logging
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)


class WhatsAppBot:
    def __init__(self):
        self.driver = None
        self.wait = None
        self.running = False
        self.processed = set()
        self.callback = None

    def log(self, message, level="INFO"):
        if self.callback:
            self.callback(message, level)
        else:
            logging.info(message)

    def start_driver(self, headless=False):
        try:
            self.log("Setting up Chrome driver...")
            chrome_options = webdriver.ChromeOptions()
            if headless:
                chrome_options.add_argument("--headless=new")
                chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            self.wait = WebDriverWait(self.driver, 600)
            
            self.log("Opening WhatsApp Web...")
            self.driver.get("https://web.whatsapp.com")
            self.log("Please scan the QR code with your phone...")
            
            self.wait.until(EC.presence_of_element_located(
                (By.XPATH, '//div[@contenteditable="true" and @data-tab]')
            ))
            self.log("✓ WhatsApp Web ready!", "SUCCESS")
            time.sleep(1)
            return True
        except Exception as e:
            self.log(f"Error starting driver: {e}", "ERROR")
            return False

    def select_chat(self, chat_name, timeout=10):
        try:
            self.log(f"Searching for chat: {chat_name}")
            search_box = self.wait.until(EC.element_to_be_clickable(
                (By.XPATH, '//div[@contenteditable="true" and @data-tab="3"]')
            ))
            search_box.click()
            time.sleep(0.2)
            search_box.clear()
            search_box.send_keys(chat_name)
            
            title = WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((By.XPATH, f'//span[@title="{chat_name}"]'))
            )
            title.click()
            time.sleep(1)
            self.log(f"✓ Selected chat: {chat_name}", "SUCCESS")
            return True
        except Exception as e:
            self.log(f"Could not select chat '{chat_name}': {e}", "ERROR")
            return False

    def _get_last_message_containers(self, max_messages=10):
        try:
            containers = self.driver.find_elements(
                By.XPATH,
                '//div[contains(@class,"message-in")] | //div[contains(@class,"message-out")]'
            )
            return containers[-max_messages:] if len(containers) >= max_messages else containers
        except Exception:
            return []

    def _extract_message_id(self, container):
        for attr in ("data-id", "data-msg-id", "data-pre-plain-text", "data-id-message"):
            try:
                val = container.get_attribute(attr)
                if val:
                    return val
            except Exception:
                pass
        try:
            text = container.text.strip()
            loc = container.location
            size = container.size
            return f"fallback::{hash((text, loc.get('x'), loc.get('y'), size.get('height'), size.get('width')))}"
        except Exception:
            return None

    def _extract_text_from_container(self, container):
        try:
            try:
                span = container.find_element(By.XPATH, './/span[@dir="ltr"]')
                return span.text.strip()
            except Exception:
                return container.text.strip()
        except Exception:
            return ""

    def send_message(self, message):
        try:
            message_box = self.driver.find_element(
                By.XPATH,
                '//div[@contenteditable="true" and (@data-tab="10" or @data-tab="6" or @data-tab="1")]'
            )
            message_box.click()
            message_box.send_keys(message)
            message_box.send_keys(Keys.ENTER)
            self.log(f"✓ Sent message: {message}", "SUCCESS")
            return True
        except Exception as e:
            self.log(f"Error sending message: {e}", "ERROR")
            return False

    def monitor_messages(self, trigger_text, reply_text, group_name=None, poll_interval=2):
        trigger_keywords = [keyword.strip().lower() for keyword in trigger_text.split(',') if keyword.strip()]
        if not trigger_keywords:
            self.log("Trigger text is empty. Please provide at least one keyword.", "ERROR")
            self.running = False
            return False

        if group_name:
            if not self.select_chat(group_name):
                self.log("Falling back to currently open chat.", "WARNING")

        self.log(f"🔍 Monitoring for triggers: {trigger_keywords}")
        self.running = True

        # Clear processed messages and prime with existing ones to only see new messages.
        self.processed.clear()
        self.log("Priming... Ignoring messages already on screen.")
        time.sleep(1)  # Give it a second to make sure chat is loaded
        try:
            initial_containers = self._get_last_message_containers(max_messages=20)
            for c in initial_containers:
                mid = self._extract_message_id(c)
                if mid:
                    self.processed.add(mid)
            self.log(f"Priming complete. Now monitoring for new messages.", "SUCCESS")
        except Exception as e:
            self.log(f"Warning: Could not prime messages. May react to old messages. Error: {e}", "WARNING")

        trigger_detected = False
        is_typing = False  # To track typing status

        # Stage 1: Wait for new trigger messages
        self.log("Stage 1: Looking for new trigger messages...")
        while self.running and not trigger_detected:
            try:
                # Check for typing status to increase polling frequency
                try:
                    # This XPath is a guess, it looks for a "typing" status in the chat header.
                    self.driver.find_element(By.XPATH, '//header//span[contains(text(), "typing")]')
                    if not is_typing:
                        self.log("Typing detected! Switching to high-frequency polling.", "INFO")
                        is_typing = True
                except Exception:
                    if is_typing:
                        self.log("Typing stopped. Reverting to normal polling.", "INFO")
                    is_typing = False

                containers = self._get_last_message_containers(max_messages=8)
                for c in containers:
                    mid = self._extract_message_id(c)
                    if not mid or mid in self.processed:
                        continue

                    text = self._extract_text_from_container(c)
                    if not text:
                        self.processed.add(mid)
                        continue
                    
                    text_lower = text.lower()
                    matched_keyword = next((kw for kw in trigger_keywords if kw in text_lower), None)

                    if matched_keyword:
                        self.log(f"✓ Trigger keyword '{matched_keyword}' matched! Message: {text[:50]}...", "SUCCESS")
                        self.processed.add(mid)
                        trigger_detected = True
                        break  # from container loop
                    else:
                        self.processed.add(mid)

                if not trigger_detected:
                    current_poll_interval = 0.2 if is_typing else poll_interval
                    time.sleep(current_poll_interval)
            except Exception as e:
                self.log(f"Exception in trigger monitoring loop: {e}", "ERROR")
                time.sleep(poll_interval)

        # Stage 2: Wait for the chat to be writable and send the message fast
        if trigger_detected and self.running:
            self.log("Stage 2: Trigger detected. Will attempt to send messages for up to 5 minutes...")
            stage2_start_time = time.time()
            at_least_one_sent = False

            # 5-minute timeout for the entire Stage 2
            while self.running and (time.time() - stage2_start_time) < 300:
                if at_least_one_sent:
                    break  # Exit the 5-minute loop if we've sent at least one message.

                try:
                    # Wait for the message box to be clickable
                    message_box = WebDriverWait(self.driver, 0.1).until(
                        EC.element_to_be_clickable((By.XPATH, '//div[@contenteditable="true" and (@data-tab="10" or @data-tab="6" or @data-tab="1")]'))
                    )
                    
                    self.log("Chat is open. Attempting to send messages...", "INFO")

                    # Try to send the first message
                    message_box.click()
                    message_box.send_keys(reply_text)
                    message_box.send_keys(Keys.ENTER)
                    self.log(f"✓ Sent first message: {reply_text}", "SUCCESS")
                    at_least_one_sent = True  # Mark success!
                    
                    time.sleep(1)

                    # Try to send the second message
                    message_box.click()  # Re-focus
                    message_box.send_keys(reply_text)
                    message_box.send_keys(Keys.ENTER)
                    self.log(f"✓ Sent second message: {reply_text}", "SUCCESS")

                except Exception:
                    # This exception means the chat is likely closed or the page is loading.
                    # We'll just wait a moment and let the 5-minute loop try again.
                    time.sleep(0.05)
            
            # After the loop
            if at_least_one_sent:
                self.log("Task complete. At least one message was sent.", "SUCCESS")
                # Wait 5 seconds before terminating
                self.log("Waiting 5 seconds before terminating...", "INFO")
                time.sleep(5)
            else:
                self.log("Timed out after 5 minutes. Could not send any messages.", "ERROR")

        self.running = False
        return at_least_one_sent

    def stop(self):
        self.running = False
        if self.driver:
            try:
                self.log("Closing browser...")
                self.driver.quit()
                self.log("✓ Browser closed.", "SUCCESS")
            except Exception as e:
                self.log(f"Error closing driver: {e}", "ERROR")


class WhatsAppAutoReplyApp:
    def __init__(self, root):
        self.root = root
        self.root.title("WhatsApp Auto-Reply Bot")
        self.root.geometry("700x600")
        self.root.resizable(True, True)
        
        self.bot = WhatsAppBot()
        self.bot.callback = self.log_message
        self.bot_thread = None
        
        self.create_widgets()
        
    def create_widgets(self):
        # Title
        title_label = tk.Label(
            self.root,
            text="WhatsApp Auto-Reply Bot",
            font=("Arial", 18, "bold"),
            fg="#075e54"
        )
        title_label.pack(pady=10)
        
        # Configuration Frame
        config_frame = ttk.LabelFrame(self.root, text="Configuration", padding=10)
        config_frame.pack(padx=20, pady=10, fill="x")
        
        # Trigger Message
        ttk.Label(config_frame, text="Trigger Message:").grid(row=0, column=0, sticky="w", pady=5)
        self.trigger_entry = ttk.Entry(config_frame, width=50)
        self.trigger_entry.insert(0, "Kimler çalışabilir?")
        self.trigger_entry.grid(row=0, column=1, pady=5, padx=5)
        
        # Reply Message
        ttk.Label(config_frame, text="Auto-Reply:").grid(row=1, column=0, sticky="w", pady=5)
        self.reply_entry = ttk.Entry(config_frame, width=50)
        self.reply_entry.insert(0, "g")
        self.reply_entry.grid(row=1, column=1, pady=5, padx=5)
        
        # Group Name (Optional)
        ttk.Label(config_frame, text="Group/Chat Name (optional):").grid(row=2, column=0, sticky="w", pady=5)
        self.group_entry = ttk.Entry(config_frame, width=50)
        self.group_entry.grid(row=2, column=1, pady=5, padx=5)
        
        # Control Buttons
        button_frame = tk.Frame(self.root)
        button_frame.pack(pady=10)
        
        self.start_button = tk.Button(
            button_frame,
            text="▶ Start Bot",
            command=self.start_bot,
            bg="#25d366",
            fg="white",
            font=("Arial", 12, "bold"),
            width=15,
            height=2
        )
        self.start_button.pack(side="left", padx=5)
        
        self.stop_button = tk.Button(
            button_frame,
            text="⏹ Stop Bot",
            command=self.stop_bot,
            bg="#dc3545",
            fg="white",
            font=("Arial", 12, "bold"),
            width=15,
            height=2,
            state="disabled"
        )
        self.stop_button.pack(side="left", padx=5)
        
        # Log Frame
        log_frame = ttk.LabelFrame(self.root, text="Activity Log", padding=10)
        log_frame.pack(padx=20, pady=10, fill="both", expand=True)
        
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=15,
            width=80,
            state="disabled",
            font=("Courier", 9)
        )
        self.log_text.pack(fill="both", expand=True)
        
        # Status Bar
        self.status_label = tk.Label(
            self.root,
            text="Status: Ready",
            bg="#f0f0f0",
            anchor="w",
            relief="sunken"
        )
        self.status_label.pack(side="bottom", fill="x")
    
    def log_message(self, message, level="INFO"):
        self.log_text.configure(state="normal")
        
        timestamp = time.strftime("%H:%M:%S")
        color = {
            "INFO": "black",
            "SUCCESS": "green",
            "WARNING": "orange",
            "ERROR": "red"
        }.get(level, "black")
        
        tag = f"tag_{level}"
        self.log_text.tag_config(tag, foreground=color)
        self.log_text.insert("end", f"[{timestamp}] {message}\n", tag)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
    
    def start_bot(self):
        trigger = self.trigger_entry.get().strip()
        reply = self.reply_entry.get().strip()
        group = self.group_entry.get().strip() or None
        
        if not trigger or not reply:
            messagebox.showerror("Error", "Please enter both trigger and reply messages!")
            return
        
        self.start_button.config(state="disabled")
        self.stop_button.config(state="normal")
        self.status_label.config(text="Status: Running...", bg="#90EE90")
        
        self.bot_thread = threading.Thread(
            target=self.run_bot,
            args=(trigger, reply, group),
            daemon=True
        )
        self.bot_thread.start()
    
    def run_bot(self, trigger, reply, group):
        try:
            if self.bot.start_driver():
                self.log_message("Open the chat you want to monitor in WhatsApp Web!")
                time.sleep(3)
                success = self.bot.monitor_messages(trigger, reply, group)
                if success:
                    self.log_message("✓ Bot completed successfully!", "SUCCESS")
                else:
                    self.log_message("Bot stopped.", "WARNING")
        except Exception as e:
            self.log_message(f"Fatal error: {e}", "ERROR")
        finally:
            self.bot.stop()
            self.root.after(0, self.reset_ui)
    
    def stop_bot(self):
        self.log_message("Stopping bot...", "WARNING")
        self.bot.stop()
        self.reset_ui()
    
    def reset_ui(self):
        self.start_button.config(state="normal")
        self.stop_button.config(state="disabled")
        self.status_label.config(text="Status: Ready", bg="#f0f0f0")


def main():
    root = tk.Tk()
    app = WhatsAppAutoReplyApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()