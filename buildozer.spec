[app]
# (str) Title of your application
title = DroidEye

# (str) Package name
package.name = droideye

# (str) Package domain (needed for android/ios packaging)
package.domain = org.example

# (str) Source code where the main.py live
source.dir = .
source.include_exts = py,ini,log
source.include_patterns = dummy.jpg

# (str) Application versioning (method 1)
version = 0.1

# (list) Application requirements
requirements = python3,kivy,cython,numpy,pyjnius 

# (str) Supported orientation (one of landscape, sensorLandscape, portrait or all)
orientation = portrait

# (list) Permissions
android.permissions = CAMERA,INTERNET,WRITE_EXTERNAL_STORAGE,FOREGROUND_SERVICE

# (str) Presplash of the application
presplash.filename = 

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0

# (str) Entry point
entrypoint = main.py

# (list) Pattern to whitelist for the whole project
android.whitelist = */*

# (int) Log level (0 = error only, 1 = info, 2 = debug (with tracebacks))
log_level = 1

# (bool) Use the SDL2 accelerated rendering
android.opengl_es2 = True 