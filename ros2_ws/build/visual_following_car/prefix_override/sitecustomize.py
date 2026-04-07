import sys
if sys.prefix == '/usr':
    sys.real_prefix = sys.prefix
    sys.prefix = sys.exec_prefix = '/home/radxa/MyDroid/ros2_ws/install/visual_following_car'
