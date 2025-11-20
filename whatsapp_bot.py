# whatsapp_auto_reply_once.py
"""
Improved WhatsApp Web auto-reply bot (educational / experimental use).
Replies once per run when the trigger text is seen in the monitored chat.
"""

import time
import logging
import signal
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class WhatsAppBot:
    def __init__(self, driver_path=None, headless=False, wait_timeout=600):
        logging.info("Setting up Chrome driver...")
        chrome_options = webdriver.ChromeOptions()
        if headless:
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        # chrome_options.add_argument(r"--user-data-dir=./whatsapp_profile")  # persist session if desired

        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        self.wait = WebDriverWait(self.driver, wait_timeout)
        self.running = True
        self.processed = set()  # set of message ids already seen/handled

    def start(self):
        logging.info("Opening WhatsApp Web...")
        self.driver.get("https://web.whatsapp.com")
        logging.info("Please scan the QR code with your phone if necessary...")
        # Wait until main chat area or search box is available
        try:
            self.wait.until(EC.presence_of_element_located(
                (By.XPATH, '//div[@contenteditable="true" and @data-tab]')
            ))
            logging.info("WhatsApp Web ready.")
            time.sleep(1)
        except Exception as e:
            logging.error("Timeout waiting for WhatsApp Web to be ready: %s", e)
            raise

    def select_chat(self, chat_name, timeout=10):
        try:
            logging.info("Searching for chat: %s", chat_name)
            search_box = self.wait.until(EC.element_to_be_clickable(
                (By.XPATH, '//div[@contenteditable="true" and @data-tab="3"]')
            ))
            search_box.click()
            time.sleep(0.2)
            search_box.clear()
            search_box.send_keys(chat_name)
            # wait and click the resulting title
            title = WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((By.XPATH, f'//span[@title="{chat_name}"]'))
            )
            title.click()
            time.sleep(1)
            logging.info("Selected chat: %s", chat_name)
            return True
        except Exception as e:
            logging.error("Could not select chat '%s': %s", chat_name, e)
            return False

    def _get_last_message_containers(self, max_messages=10):
        try:
            containers = self.driver.find_elements(
                By.XPATH,
                '//div[contains(@class,"message-in")] | //div[contains(@class,"message-out")]'
            )
            return containers[-max_messages:] if len(containers) >= max_messages else containers
        except Exception as e:
            logging.debug("Failed to get message containers: %s", e)
            return []

    def _extract_message_id(self, container):
        # try several attributes then fallback to text+position hash
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
            # try to find the LTR span commonly used for message text
            try:
                span = container.find_element(By.XPATH, './/span[@dir="ltr"]')
                return span.text.strip()
            except Exception:
                return container.text.strip()
        except Exception as e:
            logging.debug("Failed to extract text: %s", e)
            return ""

    def send_message(self, message):
        try:
            # Find message input; different data-tab values exist across WhatsApp versions
            message_box = self.driver.find_element(
                By.XPATH,
                '//div[@contenteditable="true" and (@data-tab="10" or @data-tab="6" or @data-tab="1")]'
            )
            message_box.click()
            message_box.send_keys(message)
            message_box.send_keys(Keys.ENTER)
            logging.info("Sent message: %s", message)
            return True
        except Exception as e:
            logging.error("Error sending message: %s", e)
            return False

    def monitor_messages(self, trigger_text, reply_text, group_name=None, poll_interval=2):
        """
        Monitor visible messages and auto-reply once per run when trigger_text is found.
        """
        replied_for_trigger = False  # will prevent multiple replies during this run
        trigger_lower = trigger_text.lower()

        if group_name:
            if not self.select_chat(group_name):
                logging.warning("Falling back to currently open chat.")

        logging.info("Monitoring for trigger: %r", trigger_text)

        # graceful shutdown handler
        def _signal_handler(sig, frame):
            logging.info("Received shutdown signal. Stopping...")
            self.running = False

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        while self.running:
            try:
                containers = self._get_last_message_containers(max_messages=8)
                for c in containers:
                    mid = self._extract_message_id(c)
                    if not mid:
                        continue
                    if mid in self.processed:
                        continue

                    text = self._extract_text_from_container(c)
                    if not text:
                        self.processed.add(mid)
                        continue

                    if (trigger_lower in text.lower()) and not replied_for_trigger:
                        logging.info("Trigger matched in message id=%s: %s", mid, text)
                        sent = self.send_message(reply_text)
                        if sent:
                            self.processed.add(mid)
                            replied_for_trigger = True  # reply only once per run
                            logging.info("Replied once and will not reply again this run.")
                        else:
                            logging.warning("Failed to send reply for message id=%s", mid)
                    else:
                        self.processed.add(mid)

                time.sleep(poll_interval)
            except Exception as e:
                logging.exception("Exception in monitor loop: %s", e)
                time.sleep(2)

    def close(self):
        try:
            logging.info("Closing browser...")
            self.driver.quit()
        except Exception as e:
            logging.debug("Error closing driver: %s", e)


if __name__ == "__main__":
    # --- Configuration ---
    TRIGGER_MESSAGE = "Değerli öğrenciler yarın çalışma saatlerimiz 08:00-15:00 saatleri arasında olacaktır. 25 kişi alınacaktır. Kimler çalışabilir?"
    AUTO_REPLY = "Auto Reply: BEN"
    GROUP_NAME = None  # set this to exact group/chat title to monitor a specific chat, or leave None

    bot = WhatsAppBot()
    try:
        bot.start()
        logging.info("Bot active. Open the group/chat you want to monitor in WhatsApp Web.")
        bot.monitor_messages(TRIGGER_MESSAGE, AUTO_REPLY, group_name=GROUP_NAME, poll_interval=2)
    except KeyboardInterrupt:
        logging.info("Interrupted by user.")
    except Exception as e:
        logging.exception("Fatal error: %s", e)
    finally:
        bot.close()
        logging.info("Bot closed successfully.")
