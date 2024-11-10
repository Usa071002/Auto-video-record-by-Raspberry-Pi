from datetime import datetime, timedelta
import ftplib
import json
import sys
import os
from PyQt5.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QInputDialog, QLineEdit, QMainWindow, QMessageBox, QProgressBar, QSizePolicy, QSpinBox, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSlider, QDateEdit, QTimeEdit)
from PyQt5.QtCore import QDateTime, Qt, QTimer, QDate, QTime
from PyQt5.QtGui import QFont
from picamera2 import MappedArray, Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput
from picamera2.previews.qt import QGlPicamera2
import time
import cv2
import logging
from logging.handlers import RotatingFileHandler

# FTP Server
ftp_server = "172.20.10.6"
ftp_user = "usa"
ftp_password = "somjit"
ftp_port = 2221
ftp_directory_picture = "/IE/Image"
ftp_directory_video = "/IE/Video"

# Set up logging 
log_file_path = os.path.expanduser("/home/pi/Desktop/RecordVideo.log")
max_log_size = 1 * 1024 * 1024  # 1 MB
backup_count = 5  # Number of backup files to keep

# Create a RotatingFileHandler
rotating_handler = RotatingFileHandler(log_file_path, maxBytes=max_log_size, backupCount=backup_count)
rotating_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
rotating_handler.setFormatter(formatter)

# Add the handler to the root logger
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
logger.addHandler(rotating_handler)

os.environ["LIBCAMERA_LOG_LEVELS"] = "3"

DEFAULT_CAM_NUM = 0
cam_num = DEFAULT_CAM_NUM

if len(sys.argv) == 2:
   if sys.argv[1] == "1":
       cam_num = 1
   elif sys.argv[1] == "0":
       cam_num = 0

logging.info(f"picam2 = Picamera2({cam_num})")
picam2 = Picamera2(cam_num)

preview_width = 640
preview_height = 480
preview_config_raw = picam2.create_preview_configuration(main={"size": (preview_width, preview_height)},
                                                        raw={"size": picam2.sensor_resolution},
                                                        controls={"FrameDurationLimits": (33333, 33333)})
picam2.configure(preview_config_raw)

recording = False
timer = QTimer()
target_path = ""
scheduled_timer = None  # Timer for scheduled recording

# Set timestamp overlay
def text_overlay(request):
   overlay_text = time.strftime("%F, %T")
   
   font_scale = 1  
   font_thickness = 1  
   font_thickness_outline = 2  
   font = cv2.FONT_HERSHEY_DUPLEX
   
   with MappedArray(request, "main") as m:
       # Get the size of the text to compute position
       text_size, _ = cv2.getTextSize(overlay_text, font, font_scale, font_thickness_outline)
       text_width, text_height = text_size
       
       # Compute text position
       text_x = 30
       text_y = 30 + text_height
       
       # Draw the text outline (black border)
       cv2.putText(m.array, overlay_text, (text_x - 1, text_y - 1), font, font_scale, (0, 0, 0), font_thickness_outline, cv2.LINE_AA)
       cv2.putText(m.array, overlay_text, (text_x + 1, text_y - 1), font, font_scale, (0, 0, 0), font_thickness_outline, cv2.LINE_AA)
       cv2.putText(m.array, overlay_text, (text_x - 1, text_y + 1), font, font_scale, (0, 0, 0), font_thickness_outline, cv2.LINE_AA)
       cv2.putText(m.array, overlay_text, (text_x + 1, text_y + 1), font, font_scale, (0, 0, 0), font_thickness_outline, cv2.LINE_AA)
       
       # Draw the text on top (white color)
       cv2.putText(m.array, overlay_text, (text_x, text_y), font, font_scale, (255, 255, 255), font_thickness, cv2.LINE_AA)

picam2.pre_callback = text_overlay

def create_main_window():
   window = QMainWindow()
   window.setWindowTitle("Auto video record") 
   window.setGeometry(500, 40, 1200, 1000)
   return window

# Define as a global variable
current_segment = 1
time_segment = 0

def create_preview_widget():
   global record_button, remaining_time_label

   layout = QVBoxLayout()

   # camera preview 
   global qpicamera2
   qpicamera2 = QGlPicamera2(picam2, width=preview_width, height=preview_height, keep_ar=True)
   qpicamera2.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

   global preview_checkbox
   preview_checkbox = QCheckBox("Disable Preview")
   preview_checkbox.setFont(QFont("Helvetica", 10, QFont.Bold))
   preview_checkbox.stateChanged.connect(toggle_preview_visibility)
   layout.addWidget(preview_checkbox)

   # Upload Options Checkboxes
   global upload_video_checkbox, upload_image_checkbox
   upload_video_checkbox = QCheckBox("Upload Video to Server")
   upload_video_checkbox.setFont(QFont("Helvetica", 10, QFont.Bold))
   upload_video_checkbox.setChecked(True)
   layout.addWidget(upload_video_checkbox)

   upload_image_checkbox = QCheckBox("Upload Image to Server")
   upload_image_checkbox.setFont(QFont("Helvetica", 10, QFont.Bold))
   upload_image_checkbox.setChecked(True)
   layout.addWidget(upload_image_checkbox)

   # Preview initially visible
   preview_widget = QWidget()
   preview_layout = QVBoxLayout()
   
   preview_layout.addWidget(qpicamera2)
   preview_widget.setLayout(preview_layout)
   layout.addWidget(preview_widget, 8)
   layout.addStretch()

   # Buttons Layout
   buttons_layout = QHBoxLayout()

   # Record Video Button
   global record_button
   record_button = QPushButton("Record Video")
   record_button.setFont(QFont("Helvetica", 13, QFont.Bold))
   record_button.clicked.connect(lambda: toggle_recording(
       from_date_edit.date(), from_time_edit.time(),
       to_date_edit.date(), to_time_edit.time(),
       from_date_edit, from_time_edit, to_date_edit, to_time_edit
   ))
   buttons_layout.addWidget(record_button)

   # Capture Image Button
   capture_button = QPushButton("Capture Image")
   capture_button.setFont(QFont("Helvetica", 13, QFont.Bold))
   capture_button.clicked.connect(capture_image)
   buttons_layout.addWidget(capture_button)

   layout.addLayout(buttons_layout)

   # Progress Bar
   global progress_bar
   progress_bar = QProgressBar()
   progress_bar.setMinimum(0)
   progress_bar.setMaximum(100)
   progress_bar.setValue(0)
   progress_bar.setFormat("Not Recording")
   layout.addWidget(progress_bar)

   # Time Labels
   remaining_time_label = QLabel("Remaining Time: 00:00:00")
   layout.addWidget(remaining_time_label)

   preview_widget = QWidget()
   preview_widget.setLayout(layout)
   return preview_widget

# Enable/Disable Preview
def toggle_preview_visibility(state):
   global qpicamera2
   if state == Qt.Checked:
       qpicamera2.hide()
   else:
       qpicamera2.show()

def toggle_recording(from_date, from_time, to_date, to_time, from_date_edit, from_time_edit, to_date_edit, to_time_edit):
   global recording, scheduled_timer

   try:
       if record_button.text() == "Record Video":
           record_button.setText("Cancel")
           segment_duration_checkbox.setChecked(False)  
           segment_duration_checkbox.setEnabled(False)
           segment_duration_hours.setEnabled(False)
           segment_duration_minutes.setEnabled(False)
           segment_duration_seconds.setEnabled(False)
           disable_ui_components()
           start_recording(from_date, from_time, to_date, to_time, from_date_edit, from_time_edit, to_date_edit, to_time_edit)
       elif record_button.text() == "Cancel":
           cancel_scheduled_recording()
           record_button.setText("Record Video")
           segment_duration_checkbox.setEnabled(True)
           segment_duration_hours.setEnabled(False)
           segment_duration_minutes.setEnabled(False)
           segment_duration_seconds.setEnabled(False)
           enable_ui_components()
       elif record_button.text() == "Stop Recording":
           stop_recording()
           record_button.setText("Record Video")
           segment_duration_checkbox.setEnabled(True)
           segment_duration_hours.setEnabled(False)
           segment_duration_minutes.setEnabled(False)
           segment_duration_seconds.setEnabled(False)
           enable_ui_components()
   except Exception as e:
       print(f"An error occurred: {e}")
       show_error_message("An unexpected error occurred. Please check the details and try again.", from_date_edit, from_time_edit, to_date_edit, to_time_edit)
       record_button.setText("Record Video")
       enable_ui_components()
       
def cancel_scheduled_recording():
   global scheduled_timer

   if scheduled_timer is not None and scheduled_timer.isActive():
       scheduled_timer.stop()
       scheduled_timer = None

       # Reset the button to allow starting a new recording
       record_button.setText("Record Video")
       progress_bar.setFormat("Not Recording")
       logging.info("Scheduled video recording canceled")

       current_date = QDate.currentDate()
       current_time = QTime.currentTime()
       
       from_date_edit.setDate(current_date)
       from_time_edit.setTime(current_time)
       from_time_edit.setTime(QTime.currentTime()) # .addSecs(0)
       to_date_edit.setDate(current_date)
       to_time_edit.setTime(current_time)
       to_time_edit.setTime(QTime.currentTime()) # .addSecs(0)

def start_recording(from_date, from_time, to_date, to_time, from_date_edit, from_time_edit, to_date_edit, to_time_edit):
   global recording, picam2, progress_bar, timer, scheduled_timer, start_delay, selected_directory, current_segment

   try:
       from_datetime = QDateTime(from_date, from_time).toPyDateTime()
       to_datetime = QDateTime(to_date, to_time).toPyDateTime()
       now = QDateTime.currentDateTime().toPyDateTime()

       start_delay = int((from_datetime - now).total_seconds())
       total_duration = int((to_datetime - from_datetime).total_seconds())

       if start_delay < 0:
           start_delay = 0
           total_duration = int((to_datetime - now).total_seconds())

       if total_duration <= 0:
           show_error_message("The end time must be after the current time.", from_date_edit, from_time_edit, to_date_edit, to_time_edit)
           enable_ui_components()
           return

       hours = segment_duration_hours.value()
       minutes = segment_duration_minutes.value()
       seconds = segment_duration_seconds.value()
       segment_duration = int(hours * 3600 + minutes * 60 + seconds)

       if segment_duration > total_duration and segment_duration != 0:
           show_error_message("Segment duration cannot be longer than the total recording duration.", from_date_edit, from_time_edit, to_date_edit, to_time_edit)
           enable_ui_components()
           return

       if not recording and total_duration > 0:
           resolution = resolution_combo.currentData()
           width, height = resolution

           base_directory = save_path_edit.text() or '/home/pi/Videos'
           selected_directory = base_directory  

           def create_new_folder_and_path():
               nonlocal base_directory
               actual_time = QDateTime.currentDateTime().toPyDateTime()
               date_folder = actual_time.strftime("%Y-%m-%d")
               directory = os.path.join(base_directory, date_folder)
               os.makedirs(directory, exist_ok=True)

               timestamp = actual_time.strftime("%Y-%m-%d_%H-%M-%S")
               target_path = os.path.join(directory, f"{timestamp}.mp4")
               return target_path, actual_time

           def start_segment_recording(segment_duration, from_datetime):
               global current_segment, time_segment, selected_directory  

               segment_start_time = from_datetime + timedelta(seconds=time_segment * segment_duration)
               timestamp_str = segment_start_time.strftime('%Y-%m-%d_%H-%M-%S')

               new_day = segment_start_time.strftime('%Y-%m-%d')
               current_day = os.path.basename(selected_directory)
               if new_day != current_day:
                   selected_directory = os.path.join(base_directory, new_day)
                   os.makedirs(selected_directory, exist_ok=True)

               segment_filename = f"{timestamp_str}_part{current_segment:02d}.mp4"
               segment_path = os.path.join(selected_directory, segment_filename)

               logging.info(f"Starting segment recording: {segment_path}")

               output = FfmpegOutput(segment_path)
               picam2.start_recording(H264Encoder(qp=28), output)

               # Schedule next segment
               if segment_duration > 0:
                   QTimer.singleShot(segment_duration * 1000, lambda: stop_segment_and_upload(segment_duration, from_datetime, segment_path))

       def stop_segment_and_upload(segment_duration, from_datetime, segment_path):
           global current_segment, time_segment

           if recording:
               picam2.stop_recording()

               # Upload the completed segment to FTP
               date_folder = os.path.basename(selected_directory)
               upload_file_to_ftp(segment_path, date_folder)

               current_segment += 1
               time_segment += 1

               # Check if the recording has reached the end of the total duration
               if current_segment * segment_duration < total_duration:
                   start_segment_recording(segment_duration, from_datetime)
               else:
                   logging.info("Final segment recorded and uploaded.")
                   # Any additional finalizing steps can go here

       def start_recording_now():
           global recording, start_time, current_segment, time_segment

           if not recording:
               picam2.stop()

               # Set up the recording configuration
               recording_config = picam2.create_video_configuration(main={"size": (width, height)},
                                                                   controls={"FrameDurationLimits": (41667, 41667)})
               picam2.configure(recording_config)

               current_segment = 1
               time_segment = 0
               target_path, start_time = create_new_folder_and_path()

               logging.info(f"- Video recording started: {target_path}")

               if segment_duration and segment_duration > 0:
                   start_segment_recording(segment_duration, start_time)
               else:
                   output = FfmpegOutput(target_path)
                   picam2.start_recording(H264Encoder(qp=28), output)

               recording = True
               record_button.setText("Stop Recording")

               # Initialize progress bar
               progress_bar.setValue(0)
               progress_bar.setFormat("%p%")
               progress_bar.setMaximum(total_duration)

               timer.timeout.connect(update_progress_bar)
               timer.start(1000)

               # Define remaining duration for chain timers
               remaining_duration = total_duration * 1000
               max_timer_duration_ms = 2147483647

               def chain_timers():
                   nonlocal remaining_duration
                   if remaining_duration > max_timer_duration_ms:
                       remaining_duration -= max_timer_duration_ms
                       QTimer.singleShot(max_timer_duration_ms, chain_timers)
                   else:
                       QTimer.singleShot(remaining_duration, stop_and_upload)

               def stop_and_upload():
                   stop_recording()
                   # Upload the recording when the complete recording ends

                   actual_time = QDateTime.currentDateTime().toPyDateTime()
                   date_folder = actual_time.strftime("%Y-%m-%d")
                   directory = os.path.join(base_directory, date_folder)
                   os.makedirs(directory, exist_ok=True)
                   upload_file_to_ftp(target_path, date_folder)

                   logging.info(f"File uploaded successfully: {target_path} to {date_folder}")

               chain_timers()

       scheduled_timer = QTimer()
       scheduled_timer.setSingleShot(True)
       scheduled_timer.timeout.connect(start_recording_now)
       scheduled_timer.start(max(start_delay, 0) * 1000)

   except Exception as e:
       logging.error(f"An error occurred: {e}")
       show_error_message(f"An unexpected error occurred: {e}", from_date_edit, from_time_edit, to_date_edit, to_time_edit)
       enable_ui_components()

def upload_file_to_ftp(clip_path, date_folder):
   if not upload_video_checkbox.isChecked():
       logging.info("Video upload is disabled. Skipping upload.")
       return

   logging.info(f"Attempting to upload {clip_path} to FTP server...")
   ftp = None  # Initialize ftp variable
   try:
       ftp = ftplib.FTP()
       ftp.connect(ftp_server, ftp_port)
       ftp.login(ftp_user, ftp_password)
       ftp.cwd(ftp_directory_video)

       # Ensure the date folder exists on the FTP server
       try:
           ftp.mkd(date_folder)
       except ftplib.error_perm as e:  # Catch permission error (folder already exists)
           logging.warning(f"Could not create folder {date_folder}: {e}")

       ftp.cwd(date_folder)

       with open(clip_path, 'rb') as f:
           ftp.storbinary(f'STOR {os.path.basename(clip_path)}', f)

       logging.info(f"Successfully uploaded {clip_path} to FTP server {ftp_server}/{ftp_directory_video}/{date_folder}")

   except ftplib.all_errors as e:
       logging.error(f"FTP error: {e}")
   except Exception as e:
       logging.error(f"Unexpected error uploading file {clip_path} to FTP server: {e}")
   finally:
       if ftp is not None:  # Only call quit if ftp was successfully created
           try:
               ftp.quit()
           except Exception as e:
               logging.error(f"Error closing FTP connection: {e}")

def stop_recording():
   global recording, picam2, progress_bar, timer, selected_directory, target_path, segment_duration

   if recording:
       # Stop recording and clean up
       picam2.stop_recording()
       recording = False
       progress_bar.setFormat("Not Recording")
       progress_bar.setValue(0)

       # Determine if the default directory was used
       if selected_directory == "/home/pi/Videos":
           message = "Video successfully saved to /home/pi/Videos."
       else:
           message = f"Video successfully saved to {selected_directory}."

       # Show message about recording completion
       show_record_completion_message(message)
       logging.info(f"Video recording stopped. File saved at {selected_directory}")
       
       # Stop the timer that updates the progress bar
       timer.stop()

       # Get segment duration from UI
       hours = segment_duration_hours.value()
       minutes = segment_duration_minutes.value()
       seconds = segment_duration_seconds.value()
       segment_duration = int(hours * 3600 + minutes * 60 + seconds)

       picam2.start()

       # Reset button text and UI elements
       record_button.setText("Record Video")

       # Reset Date and Time to current
       current_date = QDate.currentDate()
       current_time = QTime.currentTime()

       from_date_edit.setDate(current_date)
       from_time_edit.setTime(current_time)
       to_date_edit.setDate(current_date)
       to_time_edit.setTime(current_time)

       # Reset remaining time label
       remaining_time_label.setText("Remaining Time: 00:00:00")

   # Enable UI components after stopping the recording
   enable_ui_components()

def show_record_completion_message(message):
   completion_dialog = QMessageBox()
   completion_dialog.setIcon(QMessageBox.Information)
   completion_dialog.setText(message)
   completion_dialog.setWindowTitle("Completion")
   completion_dialog.exec_()

def update_progress_bar():
   global progress_bar, start_time, start_delay, recording

   now = QDateTime.currentDateTime().toPyDateTime()
   
   if recording:
       # Update the progress bar with elapsed time
       elapsed_time = now - start_time
       elapsed_seconds = int(elapsed_time.total_seconds())
       progress_bar.setValue(elapsed_seconds)
       
       # Calculate remaining time for recording
       remaining_time = progress_bar.maximum() - elapsed_seconds
       if remaining_time <= 0:
           # If remaining time is 0 or negative, stop the recording
           stop_recording()
           return  # Exit the function early

   else:
       # Calculate remaining time for the start delay
       remaining_time = start_delay - int((now - start_time).total_seconds())
       if remaining_time <= 0:
           remaining_time = 0  # Ensure remaining time doesn't go negative
   
   # Update the remaining time label
   if remaining_time >= 86400:  # 86400 seconds in a day
       days, remainder = divmod(remaining_time, 86400)
       hours, remainder = divmod(remainder, 3600)
       minutes, seconds = divmod(remainder, 60)
       remaining_time_label.setText(f"Remaining Time: {days}d {hours:02}h {minutes:02}m {seconds:02}s")
   elif remaining_time >= 3600:  # 3600 seconds in an hour
       hours, remainder = divmod(remaining_time, 3600)
       minutes, seconds = divmod(remainder, 60)
       remaining_time_label.setText(f"Remaining Time: {hours:02}h {minutes:02}m {seconds:02}s")
   elif remaining_time >= 60:  # 60 seconds in a minute
       minutes, seconds = divmod(remaining_time, 60)
       remaining_time_label.setText(f"Remaining Time: {minutes:02}m {seconds:02}s")
   else:
       remaining_time_label.setText(f"Remaining Time: {remaining_time}s")

def capture_image():
   global picam2

   # Create a directory for the current date
   date_str = time.strftime("%Y-%m-%d")
   output_dir = f"/home/pi/Pictures/{date_str}"
   
   # Ensure the directory exists
   os.makedirs(output_dir, exist_ok=True)

   # Create a timestamp for the image filename
   time_stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
   output = f"{output_dir}/img{cam_num}_{time_stamp}.jpg"
   logging.info(f"- Capture image: {output}")

   # Save the current callback to restore later
   original_post_callback = picam2.post_callback

   # Define a callback function for saving the image
   def save_image(request):
       try:
           with MappedArray(request, "main") as m:
               rgb_image = cv2.cvtColor(m.array, cv2.COLOR_BGR2RGB)
           cv2.imwrite(output, rgb_image)
           logging.info(f"Image saved to {output}")
           
           # Upload the image to the FTP server
           upload_image_to_ftp(output)

       except Exception as e:
           logging.info(f"Error saving image: {e}")
       finally:
           # Restore the original callback
           picam2.post_callback = original_post_callback

       # Show completion message using QMessageBox
       QTimer.singleShot(0, lambda: show_capture_completion_message(output))

   # Set the new post_callback
   picam2.post_callback = save_image

def upload_image_to_ftp(target_path):
   if not upload_image_checkbox.isChecked():
       logging.info("Image upload is disabled. Skipping upload.")
       return

   logging.info(f"Attempting to upload {target_path} to FTP server...")
   ftp = None  # Initialize ftp variable
   try:
       ftp = ftplib.FTP()
       ftp.connect(ftp_server, ftp_port)
       ftp.login(ftp_user, ftp_password)
       ftp.cwd(ftp_directory_picture)

       with open(target_path, 'rb') as f:
           ftp.storbinary(f'STOR {os.path.basename(target_path)}', f)

       logging.info(f"Successfully uploaded {target_path} to FTP server {ftp_server}/{ftp_directory_picture}")

   except ftplib.all_errors as e:
       logging.error(f"FTP error: {e}")
   except Exception as e:
       logging.error(f"Unexpected error uploading file {target_path} to FTP server: {e}")
   finally:
       if ftp is not None:  # Only call quit if ftp was successfully created
           try:
               ftp.quit()
           except Exception as e:
               logging.error(f"Error closing FTP connection: {e}")
       
def show_capture_completion_message(output):
   completion_dialog = QMessageBox()
   completion_dialog.setIcon(QMessageBox.Information)
   completion_dialog.setText(f"Image successfully saved to {output}.")
   completion_dialog.setWindowTitle("Completion")
   completion_dialog.exec_()

#===========================================================================================================

sliders_and_labels = []  # List to store slider and label references
saved_controls = {}  # Dictionary to store saved control profiles

def create_controls_tab():
   global resolution_combo, from_date_edit, from_time_edit, to_date_edit, to_time_edit, segment_duration_hours, segment_duration_minutes, segment_duration_seconds
   layout = QVBoxLayout()

   # Resolution Dropdown
   resolution_label = QLabel("Resolution:")
   resolution_label.setFont(QFont("Helvetica", 12, QFont.Bold))
   layout.addWidget(resolution_label)
   
   resolution_combo = QComboBox()
   resolution_combo.addItem("SD (640x480)", (640, 480))
   resolution_combo.addItem("HD (1280x720)", (1280, 720))
   resolution_combo.addItem("Full HD (1920x1080)", (1920, 1080))
   resolution_combo.currentIndexChanged.connect(update_resolution_from_dropdown)  
   layout.addWidget(resolution_combo)

   # From Date and Time
   date_time_label = QLabel("Schedule:")
   date_time_label.setFont(QFont("Helvetica", 12, QFont.Bold))
   layout.addWidget(date_time_label)

   from_datetime_layout = QHBoxLayout()

   from_date_edit_label = QLabel("From Date:")
   from_datetime_layout.addWidget(from_date_edit_label)

   from_date_edit = QDateEdit()
   from_date_edit.setCalendarPopup(True)
   from_date_edit.setMinimumDate(QDate.currentDate())
   from_datetime_layout.addWidget(from_date_edit)

   from_time_edit_label = QLabel("From Time:")
   from_datetime_layout.addWidget(from_time_edit_label)
   
   from_time_edit = QTimeEdit()
   from_time_edit.setDisplayFormat("HH:mm:ss")
   from_time_edit.setTime(QTime.currentTime())
   from_datetime_layout.addWidget(from_time_edit)

   layout.addLayout(from_datetime_layout)

   # To Date and Time
   to_datetime_layout = QHBoxLayout()

   to_date_edit_label = QLabel("To Date:")
   to_datetime_layout.addWidget(to_date_edit_label)

   to_date_edit = QDateEdit()
   to_date_edit.setCalendarPopup(True)
   to_date_edit.setMinimumDate(QDate.currentDate())
   to_datetime_layout.addWidget(to_date_edit)

   to_time_edit_label = QLabel("To Time:")
   to_datetime_layout.addWidget(to_time_edit_label)
   
   to_time_edit = QTimeEdit()
   to_time_edit.setDisplayFormat("HH:mm:ss")
   to_time_edit.setTime(QTime.currentTime()) 
   to_datetime_layout.addWidget(to_time_edit)

   layout.addLayout(to_datetime_layout)

   reset_button_layout = QHBoxLayout()

   # Reset Date Button
   global reset_date_button
   reset_date_button = QPushButton("Reset Date")
   reset_date_button.clicked.connect(reset_date_to_current)
   reset_button_layout.addWidget(reset_date_button)

   # Reset Time Button
   global reset_time_button
   reset_time_button = QPushButton("Reset Time")
   reset_time_button.clicked.connect(reset_time_to_current)
   reset_button_layout.addWidget(reset_time_button)

   layout.addLayout(reset_button_layout)

   # Segment Duration Spinboxes
   segment_duration_layout = QHBoxLayout()

   segment_duration_label = QLabel("Segment Duration:")
   segment_duration_label.setFont(QFont("Helvetica", 12, QFont.Bold))
   layout.addWidget(segment_duration_label)

   segment_duration_hours = QSpinBox()
   segment_duration_hours.setRange(0, 23)
   segment_duration_hours.setSuffix(" hr")
   segment_duration_hours.setValue(0)  # Default to 0 hours
   segment_duration_hours.setEnabled(False)
   segment_duration_layout.addWidget(segment_duration_hours)

   segment_duration_minutes = QSpinBox()
   segment_duration_minutes.setRange(0, 59)
   segment_duration_minutes.setSuffix(" min")
   segment_duration_minutes.setValue(0)  # Default to 0 minutes
   segment_duration_minutes.setEnabled(False)
   segment_duration_layout.addWidget(segment_duration_minutes)

   segment_duration_seconds = QSpinBox()
   segment_duration_seconds.setRange(0, 59)
   segment_duration_seconds.setSuffix(" sec")
   segment_duration_seconds.setValue(0)  # Default to 0 seconds
   segment_duration_seconds.setEnabled(False)
   segment_duration_layout.addWidget(segment_duration_seconds)

   layout.addLayout(segment_duration_layout)

   # Segment Duration CheckBox
   global segment_duration_checkbox
   segment_duration_checkbox = QCheckBox("Enable Segment Duration")
   segment_duration_checkbox.setFont(QFont("Helvetica", 10, QFont.Bold))
   segment_duration_checkbox.stateChanged.connect(lambda: toggle_segment_duration_inputs(segment_duration_checkbox))
   layout.addWidget(segment_duration_checkbox)

   # Save Path Input
   save_path_layout = QHBoxLayout()

   save_path_label = QLabel("Save Path:")
   save_path_label.setFont(QFont("Helvetica", 12, QFont.Bold))
   layout.addWidget(save_path_label)

   global save_path_edit
   save_path_edit = QLineEdit()
   save_path_edit.setPlaceholderText("Enter path or choose directory")
   save_path_layout.addWidget(save_path_edit)

   global browse_button
   browse_button = QPushButton("Browse")
   browse_button.clicked.connect(select_save_path)
   save_path_layout.addWidget(browse_button)

   layout.addLayout(save_path_layout)

   # Camera Controls
   controls_label = QLabel("Camera Control:")
   controls_label.setFont(QFont("Helvetica", 12, QFont.Bold))
   layout.addWidget(controls_label)

   sliders = [ 
       ("Brightness", 10),
       ("Contrast", 1),
       ("Saturation", 1),
       ("Sharpness", 1),
       ("ExposureValue", 1)
   ]

   if "LensPosition" in picam2.camera_controls:
       sliders.append(("LensPosition", 1))
   else:
       logging.info("LensPosition control is not available")

   default_values = {
       "Brightness": 0.0,
       "Contrast": 1.0,
       "Saturation": 1.0,
       "Sharpness": 1.0,
       "LensPosition": 1.0,
       "ExposureValue": 0.0
   }

   controls_layout = QVBoxLayout()

   for setting_name, factor in sliders:
       # Create a horizontal layout for each slider and its reset button
       h_layout = QHBoxLayout()

       # Create a vertical layout for the label and slider
       v_layout = QVBoxLayout()

       # Create the slider and label
       slider, label = create_slider(setting_name, factor)
       v_layout.addWidget(label)
       v_layout.addWidget(slider)

       # Add vertical layout to horizontal layout
       h_layout.addLayout(v_layout)

       # Create and add reset button
       reset_button = QPushButton(f"Reset")
       reset_button.clicked.connect(lambda checked, s=slider, n=setting_name: reset_to_default(s, default_values[n]))
       h_layout.addWidget(reset_button)

       controls_layout.addLayout(h_layout)
       sliders_and_labels.append((slider, label, setting_name, factor))

   layout.addLayout(controls_layout)

   controls_name_label = QLabel("Control Name:")
   controls_name_label.setFont(QFont("Helvetica", 12, QFont.Bold))
   layout.addWidget(controls_name_label)

   name_and_save_layout = QHBoxLayout()

   controls_name_edit = QLineEdit()
   controls_name_edit.setPlaceholderText("Enter control name")
   name_and_save_layout.addWidget(controls_name_edit)

   save_button = QPushButton("Save")
   save_button.clicked.connect(lambda: save_controls(controls_name_edit, controls_combobox))
   name_and_save_layout.addWidget(save_button)

   layout.addLayout(name_and_save_layout)

   controls_combobox = QComboBox()
   controls_combobox.currentIndexChanged.connect(lambda index: load_controls(controls_combobox.currentText()))
   layout.addWidget(controls_combobox)

   # Buttons layout
   buttons_layout = QHBoxLayout()

   rename_button = QPushButton("Rename")
   rename_button.clicked.connect(lambda: rename_profile(controls_name_edit, controls_combobox))
   buttons_layout.addWidget(rename_button)

   update_button = QPushButton("Update")
   update_button.clicked.connect(lambda: update_controls(controls_combobox))
   buttons_layout.addWidget(update_button)

   delete_button = QPushButton("Delete")
   delete_button.clicked.connect(lambda: delete_control(controls_combobox))
   buttons_layout.addWidget(delete_button)

   layout.addLayout(buttons_layout)

   load_saved_controls(controls_combobox)

   controls_tab = QWidget()
   controls_tab.setLayout(layout)
   return controls_tab

def update_resolution_from_dropdown(index):
   global resolution_combo, picam2, estimated_size_label
   if resolution_combo is not None:
       resolution = resolution_combo.itemData(index)
       if resolution:
           width, height = resolution
           logging.info(f"Selected Resolution: {width}x{height}")
           update_resolution(width, height)
           
def update_resolution(width, height):
   global picam2, recording

   # Stop the camera if it's recording
   if recording:
       picam2.stop_recording()
       recording = False

   # Stop the camera if it's running
   picam2.stop()

   # Configure the camera for the new resolution for both preview and recording
   preview_config = picam2.create_preview_configuration(main={"size": (width, height)},
                                                        raw={"size": (width, height)})
   picam2.configure(preview_config)
   
   # Restart the camera with the new configuration
   picam2.start()

def reset_date_to_current():
   global from_date_edit, to_date_edit
   current_date = QDate.currentDate()

   from_date_edit.setDate(current_date)
   to_date_edit.setDate(current_date)

def reset_time_to_current():
   global from_time_edit, to_time_edit
   current_time = QTime.currentTime()

   from_time_edit.setTime(current_time)
   to_time_edit.setTime(current_time)

# Error handling function
def show_error_message(message, from_date_edit, from_time_edit, to_date_edit, to_time_edit):
   global record_button

   msg_box = QMessageBox()
   msg_box.setIcon(QMessageBox.Warning)
   msg_box.setText(message)
   msg_box.setStandardButtons(QMessageBox.Ok)

   # Connect the OK button's clicked signal to a function to reset the UI
   msg_box.buttonClicked.connect(lambda: reset_ui_on_error(from_date_edit, from_time_edit, to_date_edit, to_time_edit))

   msg_box.exec_()

   # Reset the date and time fields to the current date and time
   current_date = QDate.currentDate()
   current_time = QTime.currentTime()

   from_date_edit.setDate(current_date)
   from_time_edit.setTime(current_time)
   to_date_edit.setDate(current_date)
   to_time_edit.setTime(current_time)

def reset_ui_on_error(from_date_edit, from_time_edit, to_date_edit, to_time_edit):
   record_button.setText("Record Video")
   enable_ui_components()

def toggle_segment_duration_inputs(checkbox):
   global segment_duration_hours, segment_duration_minutes, segment_duration_seconds

   if checkbox.isChecked():
       # Enable inputs if checked
       segment_duration_hours.setEnabled(True)
       segment_duration_minutes.setEnabled(True)
       segment_duration_seconds.setEnabled(True)
   else:
       # Disable inputs if unchecked
       segment_duration_hours.setEnabled(False)
       segment_duration_minutes.setEnabled(False)
       segment_duration_seconds.setEnabled(False)

selected_directory = ""

def select_save_path():
   global selected_directory
   options = QFileDialog.Options()
   options |= QFileDialog.DontUseNativeDialog
   directory = QFileDialog.getExistingDirectory(None, "Select Save Directory", "", options=options)
   if directory:
       selected_directory = directory
       save_path_edit.setText(directory)
       logging.info(f"directory: {directory}")

def disable_ui_components():
   global resolution_combo, from_date_edit, from_time_edit, to_date_edit, to_time_edit, reset_date_button, reset_time_button, segment_duration_checkbox, save_path_edit, browse_button, upload_video_checkbox
   components = [
       resolution_combo, from_date_edit, from_time_edit,
       to_date_edit, to_time_edit, reset_date_button,
       reset_time_button, segment_duration_checkbox,
       save_path_edit, browse_button, upload_video_checkbox 
   ]
   
   for component in components:
       if component is not None:
           component.setEnabled(False)
       else:
           print("Warning: A component is None and cannot be disabled.")

def enable_ui_components():
   global resolution_combo, from_date_edit, from_time_edit, to_date_edit, to_time_edit, reset_date_button, reset_time_button, segment_duration_checkbox, save_path_edit, browse_button, upload_video_checkbox
   components = [
       resolution_combo, from_date_edit, from_time_edit,
       to_date_edit, to_time_edit, reset_date_button,
       reset_time_button, segment_duration_checkbox,
       save_path_edit, browse_button, upload_video_checkbox 
   ]
   
   for component in components:
       if component is not None:
           component.setEnabled(True)
       else:
           print("Warning: A component is None and cannot be enabled.")

def reset_to_default(slider, default_value):
   global picam2, sliders_and_labels
   setting_name = [name for s, l, name, factor in sliders_and_labels if s == slider][0]
   picam2.set_controls({setting_name: default_value})
   current_value = picam2.camera_controls[setting_name][2]
   logging.info(f"Reset {setting_name} to {current_value}")
   
   # Update the corresponding slider and label
   for s, label, name, factor in sliders_and_labels:
       if s == slider:
           s.setValue(int(default_value * factor))
           label.setText(f"{name}: {default_value}")

def create_slider(setting_name, factor):
   cam_controls = picam2.camera_controls
   slider = QSlider(Qt.Horizontal)
   min_value = cam_controls[setting_name][0]
   max_value = cam_controls[setting_name][1]
   initial_value = cam_controls[setting_name][2]
   
   slider.setMinimum(int(min_value * factor))
   slider.setMaximum(int(max_value * factor))
   slider.setValue(int(initial_value * factor))
   slider.setTickPosition(QSlider.TicksBelow)
   slider.setTickInterval(1)

   label = QLabel(f"{setting_name}: {initial_value}")

   def on_value_changed():
       new_value = float(slider.value()) / factor
       label.setText(f"{setting_name}: {new_value}")

       picam2.set_controls({setting_name: new_value})
       current_value = picam2.camera_controls[setting_name][2]
       logging.info(f"{new_value} => {setting_name} = {current_value}")

   slider.valueChanged.connect(on_value_changed)

   # Enable mouse wheel to adjust the slider value
   def wheel_event(event):
       delta = event.angleDelta().y()
       if delta > 0:
           slider.setValue(slider.value() + 1)
       else:
           slider.setValue(slider.value() - 1)

   slider.wheelEvent = wheel_event

   return slider, label

def rename_profile(controls_name_edit, controls_combobox):
   """Prompts the user to rename the selected profile and handle name conflicts."""
   current_index = controls_combobox.currentIndex()
   if current_index != -1:
       current_name = controls_combobox.currentText()
       
       # Show input dialog to get new profile name
       new_name, ok = QInputDialog.getText(None, "Rename Profile", "Enter new profile name:", QLineEdit.Normal, current_name)
       
       if ok and new_name:
           # Check if the new name already exists
           existing_names = [controls_combobox.itemText(i) for i in range(controls_combobox.count())]
           
           if new_name in existing_names:
               QMessageBox.warning(None, "Rename Profile", f"A control profile with the name '{new_name}' already exists. Please choose a different name.")
           else:
               # Update the profile name in saved_controls
               saved_controls[new_name] = saved_controls.pop(current_name)
               
               # Update the combobox with the new name
               controls_combobox.setItemText(current_index, new_name)
               
               # Update the QLineEdit with the new name
               controls_name_edit.setText(new_name)
               
               # Save the updated profiles to JSON file
               save_saved_controls()
               
               logging.info(f"Renamed profile from '{current_name}' to '{new_name}'.")
       elif not ok:
           # User canceled the dialog
           logging.info("Rename canceled by the user.")
   else:
       logging.info("No profile selected to rename.")  # In case no profile is selected.

def save_controls(controls_name_edit, controls_combobox):
   """Saves a new control profile."""
   global saved_controls, sliders_and_labels, picam2

   controls_name = controls_name_edit.text().strip()

   # Check if the control name is empty
   if not controls_name:
       msg_box = QMessageBox()
       msg_box.setIcon(QMessageBox.Warning)
       msg_box.setWindowTitle("Invalid Name")
       msg_box.setText("Control name cannot be empty. Please enter a valid name.")
       msg_box.setStandardButtons(QMessageBox.Ok)
       msg_box.exec_()
       return

   # Check if the control name already exists in saved_controls
   if controls_name in saved_controls:
       msg_box = QMessageBox()
       msg_box.setIcon(QMessageBox.Warning)
       msg_box.setWindowTitle("Duplicate Name")
       msg_box.setText(f"A control profile with the name '{controls_name}' already exists. Please choose a different name.")
       msg_box.setStandardButtons(QMessageBox.Ok)
       msg_box.exec_()
       return

   # Check if the control name already exists in controls_combobox
   for index in range(controls_combobox.count()):
       if controls_combobox.itemText(index) == controls_name:
           msg_box = QMessageBox()
           msg_box.setIcon(QMessageBox.Warning)
           msg_box.setWindowTitle("Duplicate Name")
           msg_box.setText(f"A control profile with the name '{controls_name}' already exists in the combobox. Please choose a different name.")
           msg_box.setStandardButtons(QMessageBox.Ok)
           msg_box.exec_()
           return

   # Collect the current slider settings
   controls_settings = {name: float(slider.value()) / factor for slider, _, name, factor in sliders_and_labels}

   # Save a new control profile (if limit not exceeded)
   if len(saved_controls) >= 10:
       msg_box = QMessageBox()
       msg_box.setIcon(QMessageBox.Warning)
       msg_box.setWindowTitle("Maximum Limit Reached")
       msg_box.setText("You have reached the maximum number of saved control profiles (10).")
       msg_box.setStandardButtons(QMessageBox.Ok)
       msg_box.exec_()
       return

   # Save the new profile
   saved_controls[controls_name] = controls_settings
   controls_combobox.addItem(controls_name)  # Add the new profile name to the combobox.
   controls_name_edit.clear()  # Clear QLineEdit after saving.

   # Save to JSON file
   save_saved_controls()
   
def update_controls(controls_combobox):
   """Updates the selected control profile without renaming it."""
   global saved_controls, sliders_and_labels

   current_index = controls_combobox.currentIndex()
   if current_index != -1:
       current_name = controls_combobox.currentText()  # Get current profile name.
       
       # Update the profile settings under the current name
       controls_settings = {}
       for slider, _, name, factor in sliders_and_labels:
           try:
               slider_value = float(slider.value()) / factor
               controls_settings[name] = slider_value
           except Exception as e:
               print(f"Error updating slider settings: {e}")

       saved_controls[current_name] = controls_settings

       # Save to JSON file
       save_saved_controls()

       logging.info(f"Updated control profile: {current_name}")

       # Show QMessageBox to inform user that the control settings were updated
       msg_box = QMessageBox()
       msg_box.setIcon(QMessageBox.Information)
       msg_box.setWindowTitle("Update Successful")
       msg_box.setText(f"Control setting for '{current_name}' have been updated successfully.")
       msg_box.setStandardButtons(QMessageBox.Ok)
       msg_box.exec_()

   else:
       logging.info("No profile selected to update.")

def load_saved_controls(controls_combobox):
   global saved_controls

   try:
       with open("/home/pi/saved_controls.json", "r") as file:
           saved_controls = json.load(file)
   except FileNotFoundError:
       saved_controls = {}
   except json.JSONDecodeError:
       saved_controls = {}

   controls_combobox.clear()
   controls_combobox.addItems(saved_controls.keys())

def delete_control(controls_combobox):
   global saved_controls

   current_text = controls_combobox.currentText()
   if current_text:
       msg_box = QMessageBox()
       msg_box.setIcon(QMessageBox.Warning)
       msg_box.setWindowTitle("Delete Profile")
       msg_box.setText(f"Are you sure you want to delete the profile '{current_text}'?")
       msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
       result = msg_box.exec_()

       if result == QMessageBox.Yes:
           if current_text in saved_controls:
               del saved_controls[current_text]
               controls_combobox.removeItem(controls_combobox.currentIndex())
               save_saved_controls()
               logging.info(f"Deleted control profile: {current_text}")
           else:
               logging.info(f"Profile '{current_text}' does not exist.")
       else:
           logging.info("Deletion canceled.")

def save_saved_controls():
   import json
   with open("/home/pi/saved_controls.json", "w") as file:
       json.dump(saved_controls, file, indent=4)

def load_controls(controls_name):
   global saved_controls, sliders_and_labels, picam2
   
   if controls_name in saved_controls:
       controls_settings = saved_controls[controls_name]
       
       for slider, label, name, factor in sliders_and_labels:
           if name in controls_settings:
               new_value = controls_settings[name]
               slider.setValue(int(new_value * factor))
               label.setText(f"{name}: {new_value:.2f}")
               
               # Update camera control
               try:
                   picam2.set_controls({name: new_value})
                   logging.info(f"Loaded {name} = {new_value:.2f}")
               except Exception as e:
                   logging.info(f"Error setting control {name}: {e}")
               
               try:
                   current_value = picam2.camera_controls[name][2]
                   logging.info(f"Loaded {name} = {current_value:.2f} from controls '{controls_name}'")
               except KeyError:
                   logging.info(f"Control {name} not found in camera controls")
   else:
       logging.info(f"Control profile '{controls_name}' not found.")

def main():
   app = QApplication(sys.argv)
   
   main_window = create_main_window()
   
   main_layout = QHBoxLayout()
   
   preview_widget = create_preview_widget()
   controls_tab = create_controls_tab()
   
   main_layout.addWidget(preview_widget, 7)  # Adjusted size ratio
   main_layout.addWidget(controls_tab, 2)    # Adjusted size ratio
   
   central_widget = QWidget()
   central_widget.setLayout(main_layout)
   main_window.setCentralWidget(central_widget)
   
   main_window.show()
   picam2.start()
   
   sys.exit(app.exec_())

if __name__ == '__main__':
   main()