#!/usr/bin/env python3

import os
import sip
import rospy
import rospkg

from qt_gui.plugin import Plugin
from python_qt_binding import loadUi
from python_qt_binding.QtWidgets import QWidget, QFileSystemModel, QTreeView, QDirModel, QTreeWidgetItemIterator, QPushButton
from python_qt_binding.QtWidgets import QVBoxLayout
from python_qt_binding.QtGui import QIcon
import python_qt_binding.QtGui as QtGui
import python_qt_binding.QtCore as QtCore
from std_srvs.srv import Empty, EmptyResponse
import subprocess
from flexbe_msgs.msg import OutcomeRequest, BehaviorLog
from std_msgs.msg import String
import traceback
import glob
import re
import shutil
import datetime
import osrt_ros

rospack = rospkg.RosPack()
MY_pkg_path = rospack.get_path("rqt_acquisition")
sample_notebook=os.path.join(MY_pkg_path, "standard_analysis.ipynb")
new_header = """

### NAME OF ACTIVITY: {activity}

SESSION ID: {session_num}

SUBJECT ID: {subject}

GENERATED DATE: {date_string}

"""


def text_to_ipynblines(text):
    new_str = ""
    for line in text.split("\n"):
        new_str +='"' + line + r'\n",'+'\n'

    return new_str

def generate_custom_ipynb(new_ipynb_name, updated_header, activity,subject,session_num,weight):
    #shutil.copy(sample_notebook, new_ipynb_name)
    with open(sample_notebook,'r') as file:
        my_notebook = file.read()
    my_notebook = my_notebook.replace("ik.sto","ik_lower.sto")
    my_notebook = my_notebook.replace("%%ACTION%%",activity)
    #rospy.logwarn(my_notebook)
    my_notebook = my_notebook.replace("%%SUBJECT%%",subject)
    #rospy.logerr(my_notebook)
    my_notebook = my_notebook.replace("%%WEIGHT%%",str(weight))
    #rospy.loginfo(my_notebook)
    date_ = datetime.datetime.now()
    date_str = date_.strftime("%Y-%m-%d %I:%M:%S %p")
    format_dic = {"session_num": session_num,"subject":subject,"activity":activity, "date_string":date_str}
    my_notebook = my_notebook.replace(r'"%%HEADER%%\n",',text_to_ipynblines(updated_header.format(**format_dic)))
    #rospy.logwarn(my_notebook)
    rospy.loginfo(f"generating notebook: {new_ipynb_name}")
    with open(new_ipynb_name,'w') as file:
        file.write(my_notebook)



def segment_activity_from_counter(activity_name):
    counter = 0
    match = re.match(r"([a-z]+)([0-9]+)", activity_name, re.I)
    if match:
        rospy.loginfo("found a trial counter, will remove it to get the activity name")
        items = match.groups()
        if len(items) >= 2:
            activity_name = "".join(items[:-1])
            counter = int(items[-1])
        else:
            rospy.logerr(activity_name)
            rospy.logerr(items)
    else:
        rospy.logwarn("regex didnt find counter!"+activity_name)

    return activity_name, counter

def print_events(obj):
    rospy.logdebug(obj)
    a = dir(obj)
    for prop in a:
        if "Event" in prop:
            rospy.logdebug(prop)

def check_if_lib_moment_arm_exists_at_path(some_file_with_complete_path):
    directory = os.path.dirname(some_file_with_complete_path)
    file_shenanigans = os.path.basename(some_file_with_complete_path)
    filename, extension = os.path.splitext(file_shenanigans)
    rospy.logdebug(directory)
    rospy.logdebug(file_shenanigans)
    desired_lib_name = construct_lib_name_from_osim_name(filename)

    #lib_path =os.path.join(directory,desired_lib_name)
    lib_path =os.path.join("/catkin_ws/devel/lib/",desired_lib_name)
    return os.path.exists(lib_path), lib_path

def construct_lib_name_from_osim_name(osim_name):
    return "libMomentArm_"+osim_name+".so"

def create_path_label(subject_id, activity_name, session_num):
    rospy.logdebug(subject_id)
    rospy.logdebug(activity_name)
    rospy.logdebug(session_num)
    rospy.logwarn("ATTENTION! create_path_label function has a hardcoded local path!!! PLEASE CHANGE!")
    return os.path.join("/srv/host_data/RTValidation", subject_id,session_num)

def validate_model(model_file):
    #return True

    rospy.loginfo(f"trying to validate model {model_file}")
    ## this is totally specific to AR and the way the things are working right now
    ## I will check if I have C7 defined, because if it doesn't using AR will crash the system
    with open(model_file) as f:
        contents = f.read()
        if "C7" in contents:
            return True
        else:
            return False


def load_ui(filename):
    file = QFile(filename)
    file.open(QFile.ReadOnly)
    widget = QUiLoader().load(file)
    file.close()
    return widget



class VioPlugin(Plugin):

    def __init__(self, context):
        self.units_available = 0 #TODO: read other todo
        super(VioPlugin, self).__init__(context)
        # Give QObjects reasonable names
        self.setObjectName('VioPlugin')

        self.weight = -1
        
        self.sr = rospy.Service("/rqt_acquisition/set_running", Empty, self.set_running)
        self.sw = rospy.Service("/rqt_acquisition/update_widgets", Empty, self.update_widget_states)
        self.sp = rospy.Service("/rqt_acquisition/refresh_paths", Empty, self.refresh_path_service)

        #mm = ["thorax","radius"] ## TODO: this shouldnt be hard coded
        self.reset_rov = []
        self.calib_rov = []


        # Process standalone plugin command-line arguments
        from argparse import ArgumentParser
        parser = ArgumentParser()
        # Add argument(s) to the parser.
        parser.add_argument("-q", "--quiet", action="store_true",
                      dest="quiet",
                      help="Put plugin in silent mode")
        args, unknowns = parser.parse_known_args(context.argv())
        if not args.quiet:
            print('arguments: ', args)
            print('unknowns: ', unknowns)

        # Create QWidget
        #self._widget = QWidget()

        self._widget = QWidget()
        self._widget.setObjectName('VioPluginUi')
        # Get path to UI file which should be in the "resource" folder of this package
        ui_file = os.path.join(rospkg.RosPack().get_path('rqt_acquisition'), 'resource', 'VioPlugin.ui')
        # Extend the widget with all attributes and children from UI file
        loadUi(ui_file, self._widget)
        #layout = QVBoxLayout()
        #self._widget.setLayout(layout)
        # Give QObjects reasonable names
        # Show _widget.windowTitle on left-top of each plugin (when 
        # it's set in _widget). This is useful when you open multiple 
        # plugins at once. Also if you open multiple instances of your 
        # plugin at once, these lines add number to make it easy to 
        # tell from pane to pane.
        if context.serial_number() > 1:
            self._widget.setWindowTitle(self._widget.windowTitle() + (' (%d)' % context.serial_number()))
        # Add widget to the user interface



        # after loading your main window:
        self.calibration_ui = QWidget()
        ui_file2 = os.path.join(rospkg.RosPack().get_path('rqt_acquisition'), 'resource', 'Calibration.ui')
        loadUi(ui_file2, self.calibration_ui)
        
        layout = QVBoxLayout(self._widget.calibration)
        layout.addWidget(self.calibration_ui)

        self._widget.start_button.setIcon(QIcon.fromTheme('media-record'))
        self._widget.start_button.clicked[bool].connect(self._handle_start_clicked)
        self._widget.stop_button.setIcon(QIcon.fromTheme('media-playback-stop'))
        self._widget.stop_button.clicked[bool].connect(self._handle_stop_clicked)
        self._widget.set_and_go_button.setIcon(QIcon.fromTheme('media-playback-start'))
        self._widget.set_and_go_button.clicked[bool].connect(self._handle_set_and_go_clicked)
        self._widget.another_button.setIcon(QIcon.fromTheme('media-skip-forward'))
        self._widget.another_button.clicked[bool].connect(self._handle_another_clicked)

        self.calibration_ui.calibrate_button.clicked[bool].connect(self._handle_calibrate_clicked)
        self.calibration_ui.calib_vio_button.clicked[bool].connect(self._handle_calib_vio_clicked)
        self.calibration_ui.recalibrate_rovio_button.clicked[bool].connect(self._handle_recalibrate_rovio_clicked)
        self.calibration_ui.don_button.clicked[bool].connect(self._handle_don_clicked)
        self._widget.do_set_name_button.clicked[bool].connect(self._handle_do_set_name_clicked)

        self._widget.generate_lib_moment_arm_button.clicked[bool].connect(self._handle_lib_moment_clicked)
        self._widget.generate_action_notebook_button.clicked[bool].connect(self._generate_notebook_clicked)
        
        self.calibration_ui.srv1_button.clicked[bool].connect(self._srv1_clicked)
        self.calibration_ui.srv2_button.clicked[bool].connect(self._srv2_clicked)

        self.flexbe_commander_publisher = rospy.Publisher("/flexbe/command/transition", OutcomeRequest, queue_size=1)
        self.state_subscriber           = rospy.Subscriber("/flexbe/behavior_update", String, callback=self.update_state, queue_size=1)
        self.flexbe_log_subscriber           = rospy.Subscriber("/flexbe/log", BehaviorLog, callback=self.update_log, queue_size=1)

        if True:
            model = QFileSystemModel()


            models_path ="/srv/shared/" 
            if os.path.exists(models_path):
                model.setRootPath(models_path)
            else:
                model.setRootPath("/srv/host_data/")
            model.removeColumns(1,2)
            model.setNameFilters(["*.osim"])
            model.setNameFilterDisables(False)
        if False:
            rospy.logdebug(dir(model))
            rospy.logdebug(model.columnCount())
            rospy.logdebug(model.removeColumn(1))
            rospy.logdebug(model.beginRemoveColumns)
            rospy.logdebug(help(model.beginRemoveColumns))
            rospy.logdebug(model.columnCount())
            rospy.logdebug(model.rootPath())
            rospy.logdebug(model.rootDirectory())
            #rospy.logdebug(model.size())
            #rospy.logdebug(model.event())


        self.my_namespace = 'rqt_acquisition'

        self.calibration_ui.calibrate_button.setStyleSheet("font-size: 24px;");
        self._widget.start_button.setStyleSheet("font-size: 24px;");
        self._widget.stop_button.setStyleSheet("font-size: 24px;");

        self.model_path = ""
        self.lib_path = ""
        self.lib_path_exists = False
        self.activity_name = ""
        self.subject_id = ""
        self.session_num = ""
        self.save_path = ""
        self.description_text = ""
        self.activity_counter = 0
        self.ori_list = ["thoRax","radIus"]

        self.set_from_params()
        self.update_paths()
        rospy.logwarn(f"what text is in the widget? {self._widget.resolved_path_name.text()}")
        
        if True: ## we update the directory widget after getting the new values
            #rospy.logerr(dir(self._widget.model_selector.SelectedClicked))
            self._widget.keyPressEvent = self._handle_model_changed_keypress

            self._widget.model_selector.setModel(model)
            self._widget.model_selector.setColumnHidden(1,True)
            self._widget.model_selector.setColumnHidden(2,True)
            self._widget.model_selector.setColumnHidden(3,True)
            self._widget.model_selector.expandAll()
            
            self._widget.model_selector.viewport().installEventFilter(self)

        #hopefully ori_list is already set properly after the setup
        self.update_ori_list()

        print_events(self._widget.activity_name)
        
        self._widget.activity_name.textChanged.connect(self.update_paths)
        self._widget.session_name.textChanged.connect(self.update_paths)
        self._widget.subject_id_name.textChanged.connect(self.update_paths)
        self._widget.description.textChanged.connect(self.update_paths)
        self._widget.resolved_path_name.textChanged.connect(self.update_path_higher_priority)
        self._widget.units_selected_name.textChanged.connect(self.update_ori_from_text_change)
        #self._widget.subject_id_name.changeEvent = self.update_paths

            #print_events(self._widget.model_selector)
        context.add_widget(self._widget)
        
        #layout = self._widget.layout()
        #layout = QVBoxLayout(self._widget)
        #layout.addWidget(self.calibration_ui)
        #context.add_widget(self.calibration_ui)
        
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.timerEvent)
        self.timer.start(1000)
        self.disable_buttons()

        self.model_bodies = [] ## this should contain the model bodies once we have erm some model
        self.units_available = 2 ## TODO: now it is only 2, silver and rpi5-ubuntu, we need to make this variable at some point and pass this list too.

    def update_ori_from_text_change(self):
        rospy.loginfo("update ori text changed")
        #self.update_things()  ## this is being called for every event anyway
        self.update_units()
        self.set_to_params()

    def update_ori_list(self):
        self.reset_rov = []
        self.calib_rov = []
        for body in self.ori_list:
            self.reset_rov.append( rospy.ServiceProxy(f"/{body}/rovio/reset", Empty) )
            self.calib_rov.append( rospy.ServiceProxy(f"/{body}/calib", Empty) )

    def disable_buttons(self):
        self.calibration_ui.calibrate_button.setEnabled(False)
        self._widget.start_button.setEnabled(False)
        self._widget.stop_button.setEnabled(False)
        self._widget.another_button.setEnabled(False)
        self._widget.activity_group.setEnabled(False)
        self.calibration_ui.don_button.setEnabled(False)
        self.calibration_ui.recalibrate_rovio_button.setEnabled(False)
        self.calibration_ui.calib_vio_button.setEnabled(False)
        self._widget.do_set_name_button.setEnabled(False)
        self._widget.generate_action_notebook_button.setEnabled(False)

    def update_state(self, msg):
        self.disable_buttons()
        self._widget.current_state_text.setText("Current State:"+msg.data)
        if msg.data == "/Get_Ready_For_Calibration":
            self.calibration_ui.calibrate_button.setEnabled(True)
        if msg.data == "/Start_Recording_Question_Mark":
            self._widget.start_button.setEnabled(True)
        if "/Recording" in msg.data:
            self._widget.stop_button.setEnabled(True)
        if msg.data == "/Record_Another":
            self._widget.generate_action_notebook_button.setEnabled(True)
            self._widget.another_button.setEnabled(True)
        if msg.data == "/Say_To_Change_Name":
            self.update_paths()
            self._widget.activity_group.setEnabled(True)

        if "don_cameras" in msg.data:
            self.calibration_ui.don_button.setEnabled(True)
        if "calib_vio" in msg.data:
            self.calibration_ui.calib_vio_button.setEnabled(True)
        if "Say_To_Change_Name" in msg.data:
            self._widget.do_set_name_button.setEnabled(True)
        


    def set_running(self, req = None):    
        try:
            ## check if stuff works out:
            if not os.path.exists(self.model_path):
                rospy.logfatal("Cannot find model in the specified path. Every node will fail.")
                raise Exception("Model Path doesn't exist! Every node will fail.")
            if not self.lib_path_exists:
                ## maybe I can set it to a default library or something...
                rospy.logwarn("Moment Arm Library not found at current path. SO will fail.")
            if not validate_model(self.model_path):
                raise Exception("This model is invalid!")

            self._widget.model_group.setEnabled(False)
            #self.timer.start(500) ## in ms
        except:
            traceback.print_exc()

        return EmptyResponse()

    def set_from_params(self):
        rospy.logdebug("set_from_params")
        if rospy.has_param(self.my_namespace):
            my_dic = rospy.get_param(self.my_namespace)
            for key, value in my_dic.items():
                rospy.logwarn(f"set_from_params:: {self.my_namespace}/{key}: {value} ")
                setattr(self, key, value)
            self._was_set_to_params = False ## this means that my information is NOT current
        else:
            rospy.logwarn("rqt_acquisition params are not set, they will be set to something.")
            self.set_to_params()
        self.update_widget_states()
            
    def set_to_params(self):
        #rospy.loginfo("set_to_params")
        the_params = {  "model_path"        :self.model_path,
                        "lib_path"          :self.lib_path,
                        "activity_name"     :self.activity_name,
                        "subject_id"        :self.subject_id,
                        "session_num"       :self.session_num,
                        "save_path"         :self.save_path,
                        "description_text"  :self.description_text,
                        "ori_list"          :self.ori_list,
                        "weight"            :self.weight}

        rospy.logdebug(the_params)
        for key, value in the_params.items():
            rospy.set_param(f"/{self.my_namespace}/{key}", value )
        

        ### btw, I am runnign this all the time, it's fast, so it doesnt really matter, but maybe consider optimizing
        rospy.logdebug("what I got: "+str(rospy.get_param(f"/{self.my_namespace}")))
        #self.update_widget_states()
        
    def refresh_path_service(self, req = None):
        self.set_from_params()
        return EmptyResponse()

    def update_widget_states(self, req = None):
        rospy.loginfo("updating widget states")
        self._widget.resolved_path_name.setText(   self.save_path )
        self._widget.model_selected_name.setText(self.model_path)
        self.lib_path_exists, self.lib_path = check_if_lib_moment_arm_exists_at_path(self.model_path)
        ##TODO: color change is not repainting, so it was removed.
        if self.lib_path_exists:
            self._widget.lib_moment_arm_text.setText("[V] "+self.lib_path)
            #self._widget.lib_moment_arm_text.setStyleSheet("color: green;")
        else:
            self._widget.lib_moment_arm_text.setText("[X] "+self.lib_path)
            #self._widget.lib_moment_arm_text.setStyleSheet("color: red;")
        #self._widget.lib_moment_arm_text.repaint()
        #self._widget.lib_moment_arm_text.parentWidget().repaint()
        #self._widget.lib_moment_arm_text.parentWidget().parentWidget().repaint()
        #self._widget.repaint()
        self._widget.subject_id_name.setText(self.subject_id)
        self._widget.activity_name.setText(self.activity_name)
        self._widget.session_name.setText(self.session_num)

        ## now update the tree widget

        #model = self._widget.model_selector.model()
        #model.setRootPath(self.model_path)
        #self._widget.model_selector.setModel(model)
        #self._widget.model_selector.reset()
        #self._widget.model_selector.update()
        #index = self._widget.model_selector.selectedIndexes()[0]
        #rospy.logdebug(index)
        #self._widget.model_selector.setExpanded(index, True)
        

        #https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QTreeWidgetItemIterator.html#PySide6.QtWidgets.QTreeWidgetItemIterator
        
        #it = QTreeWidgetItemIterator(self._widget.model_selector)
        #while it:
        #    index = self._widget.model_selector.indexFromItem(it)
        #    info = self._widget.model_selector.model().fileInfo(index)
        #    if info.absoluteFilePath() == self.model_path:
        #        (it).setSelected(True)
        #        break
        #    it += 1
        
        self._widget.repaint()

        return EmptyResponse()

    def update_path_higher_priority(self, event=None):

        self.save_path = self._widget.resolved_path_name.text()
        self.activity_name = self._widget.activity_name.text()
        self.description_text = self._widget.description.toPlainText()
        self.set_to_params()

    def update_paths(self, event=None):
        ## update save_path from subjectid activity and session
        self.subject_id = self._widget.subject_id_name.text()
        self.activity_name = self._widget.activity_name.text()
        self.session_num = self._widget.session_name.text()
                

        self.save_path = create_path_label( self.subject_id, 
                                            self.activity_name,
                                            self.session_num
                ) 
        self._activity_name_bare, self.activity_counter = segment_activity_from_counter(self.activity_name)

        self._widget.resolved_path_name.setText(   self.save_path )
        self.activity_name = self._widget.activity_name.text()
        self.description_text = self._widget.description.toPlainText()
        self.set_to_params()

    def update_things(self, event=None):
        self.model_path = self._widget.model_selected_name.text()
        self.model_bodies= osrt_ros.parse_bodies(self.model_path)
        self._widget.model_bodies_text.setText(repr(self.model_bodies))
        self.lib_path_exists, self.lib_path = check_if_lib_moment_arm_exists_at_path(self.model_path)
        if self.lib_path_exists:
            self._widget.lib_moment_arm_text.setText("[V] "+self.lib_path)
        else:
            self._widget.lib_moment_arm_text.setText("[X] "+self.lib_path)
        self.set_to_params()
        
        #self._widget.repaint()
    
    def update_units(self):

        try:
            #print("UPDATING UNITS")
            maybe_ori_list = self._widget.units_selected_name.text()
            if "[" in maybe_ori_list and "]" in maybe_ori_list:
                maybe_more_ori_list = eval(maybe_ori_list)
                if type(maybe_more_ori_list) == list: #it is or returns a list, we are a go.
                    print("ima list")
                    ori_list = maybe_more_ori_list
                    for lbody in ori_list:
                        if lbody not in self.model_bodies:
                            print("found a body in your list not in the model body list, unfortunately")
                            return
                    ##if we got here we have all the list bodies in the model bodies
                    lbodies = len(ori_list)
                    mbodies = len(self.model_bodies)
                    
                    self._widget.units_selected.setText(f"Units [{lbodies}/{self.units_available}]")
                    if lbodies == self.units_available:
                        self._widget.units_selected.setStyleSheet("color: green;");
                        self.ori_list = ori_list
                        self.update_ori_list()
                #self.update_widget_states()

        except:
            self._widget.units_selected.setStyleSheet("color: red;");
            self._widget.repaint()
            #traceback.print_exc()


    def timerEvent(self):
        #rospy.loginfo("timerEvent triggered")
        self._widget.update()

    def _generate_notebook_clicked(self):
        rospy.loginfo("generate notebook button clicked")
        ## parse bag files if they exist
        activity_name, _ = segment_activity_from_counter(self.activity_name)

        source_topic = "/id_node"
        for bag_file in glob.glob(os.path.join(self.save_path,"*.bag")):
            if activity_name in bag_file:
                p = subprocess.Popen(["rostopic","echo","-b", bag_file,"-p",source_topic], stdout=subprocess.PIPE) #> timings.txt])
                out, err = p.communicate()
                with open(bag_file+"_timings.txt", 'wb') as timings:
                    timings.write(out)

        new_ipynb_name =os.path.join(self.save_path, "%s_analysis.ipynb"%(activity_name)) 
        rospy.loginfo(new_ipynb_name)
        generate_custom_ipynb(new_ipynb_name,new_header,activity_name,self.subject_id,self.session_num, self.weight)

    def _handle_lib_moment_clicked(self):
        rospy.loginfo("lib_moment clicked!")
        self._widget.generate_lib_moment_arm_button.setEnabled(False)
        previous_text = self._widget.generate_lib_moment_arm_button.text()
        self._widget.generate_lib_moment_arm_button.setText("Generating...")

        path_to_generate_lib_at = os.path.splitext(self.lib_path)[0]
        
        log.error("ATTENTION: Lib moment arm caller has hardcoded paths!! ")
        shutil.copy(self.model_path,"/srv/host_data/models/")
        #subprocess.run(f"python3 /catkin_ws/src/ros_biomech/lib_moment_arm/symbolic_moment_arm_v40.py --model={self.model_path} --results_destination={path_to_generate_lib_at}",shell=True)
        subprocess.run(f"/usr/bin/catkin_build_ws.bash --pkg lib_moment_arm -DSINGLE_TARGET_FILE={self.model_path}",shell=True)
        #my_so_files = os.path.join(path_to_generate_lib_at,"*.so")
        #for fi in my_so_files:
        #    shutil.copy(fi, self.lib_path)

        self._widget.generate_lib_moment_arm_button.setText(previous_text)
        self._widget.generate_lib_moment_arm_button.setEnabled(True)
        self.update_things()
    
    def _handle_start_clicked(self):
        rospy.loginfo("start clicked!")

        start_msg = OutcomeRequest()
        start_msg.outcome = 0
        start_msg.target = 'Start_Recording_Question_Mark'
        self.flexbe_commander_publisher.publish(start_msg)

        self.set_from_params()
        self.set_running()
        self._widget.start_button.setEnabled(False)


    def _handle_stop_clicked(self):
        rospy.loginfo("stop clicked!")
        self._widget.stop_button.setEnabled(False)
        stop_msg = OutcomeRequest()
        stop_msg.outcome = 0
        stop_msg.target = 'Recording'
        self.flexbe_commander_publisher.publish(stop_msg)
        self.set_from_params()


    def _handle_model_changed_keypress(self,event):

        key = event.key()
        ## this only works for keyboard presses
        if key == self._widget.model_selector.SelectedClicked:
            rospy.loginfo("SelectedClicked")
        if key == self._widget.model_selector.DoubleClicked:
            rospy.loginfo("DoubleClicked")
        rospy.loginfo(dir(event))
        rospy.loginfo(key)

    def _handle_set_and_go_clicked(self):
        rospy.loginfo("set and go clicked!")
        ## check if model exists first 
        if not os.path.exists(self.model_path):
            ## how a dialog?
            return
        try:
            command_msg = OutcomeRequest()
            command_msg.outcome = 0
            command_msg.target = 'Load_Combined_Perspective'
            self.flexbe_commander_publisher.publish(command_msg)
            #self._widget.model_group.setEnabled(Falseart)
        except:
            traceback.print_exception()
        
        self._widget.set_and_go_button.setEnabled(False)
        self._widget.units_selected_name.setEnabled(False)
    
    def _handle_another_clicked(self):
        rospy.loginfo("another clicked!")
        self.activity_counter+=1
        self.activity_name = self._activity_name_bare + str(self.activity_counter)
        self.set_to_params()
        self.update_widget_states()
        try:
            command_msg = OutcomeRequest()
            command_msg.outcome = 0
            command_msg.target = 'Record_Another'
            self.flexbe_commander_publisher.publish(command_msg)
            #self._widget.model_group.setEnabled(Falseart)
            self._widget.another_button.setEnabled(False)
        except:
            traceback.print_exception()

    def _handle_calibrate_clicked(self):
        rospy.loginfo("calibration_ui.calibrate_button clicked!")
        try:
            command_msg = OutcomeRequest()
            command_msg.outcome = 0
            command_msg.target = 'Get_Ready_For_Calibration'
            self.flexbe_commander_publisher.publish(command_msg)
            #self._widget.model_group.setEnabled(Falseart)
            self.calibration_ui.calibrate_button.setEnabled(False)
        except:
            traceback.print_exception()
            


    def _handle_do_set_name_clicked(self):
        rospy.loginfo("do_set_name_button clicked!")
        try:
            self._widget.do_set_name_button.setEnabled(False)
            command_msg = OutcomeRequest()
            command_msg.outcome = 0
            command_msg.target = 'Say_To_Change_Name'
            self.flexbe_commander_publisher.publish(command_msg)
            #self._widget.model_group.setEnabled(Falseart)
        except:
            traceback.print_exception()
    def _handle_don_clicked(self):
        rospy.loginfo("calibration_ui.don_button clicked!")
        try:
            self.calibration_ui.don_button.setEnabled(False)
            command_msg = OutcomeRequest()
            command_msg.outcome = 0
            command_msg.target = 'don_cameras'
            self.flexbe_commander_publisher.publish(command_msg)
            #self._widget.model_group.setEnabled(Falseart)
        except:
            traceback.print_exception()
    def _handle_calib_vio_clicked(self):
        rospy.loginfo("calibration_ui.calib_vio_button clicked!")
        try:
            self.calibration_ui.calib_vio_button.setEnabled(False)
            command_msg = OutcomeRequest()
            command_msg.outcome = 0
            command_msg.target = 'calib_vio'
            self.flexbe_commander_publisher.publish(command_msg)
            #self._widget.model_group.setEnabled(Falseart)
        except:
            traceback.print_exception()
    def _handle_recalibrate_rovio_clicked(self): ###eh this is different!
        rospy.loginfo("calibration_ui.recalibrate_rovio_button clicked!")
        try:
            self.calibration_ui.recalibrate_rovio_button.setEnabled(False)
            command_msg = OutcomeRequest()
            command_msg.outcome = 0
            command_msg.target = 'recalibrate_rovio'
            self.flexbe_commander_publisher.publish(command_msg)
            #self._widget.model_group.setEnabled(Falseart)
        except:
            traceback.print_exception()
    
    def _srv1_clicked(self): ###eh this is different!
        rospy.loginfo("calibration_ui.srv1_button clicked!")
        try:
            for some_srv in self.reset_rov:
                some_srv()
        except:
            traceback.print_exception()
    
    def _srv2_clicked(self): ###eh this is different!
        rospy.loginfo("calibration_ui.srv2_button clicked!")
        try:
            for some_srv in self.calib_rov:
                some_srv()
            
        except:
            traceback.print_exception()

    def eventFilter(self, source, event):
        rospy.logdebug("something")
        self.update_things()
        #self.update_paths()
        if not sip.isdeleted(self._widget.model_selector) and source is self._widget.model_selector.viewport():
            rospy.logdebug("i am from the model selector")
            if isinstance(event, QtGui.QMouseEvent):
                rospy.logdebug("i am a mouse event")
                #rospy.loginfo(event.buttons())
                #rospy.loginfo(dir(event))
                #rospy.loginfo(dir(event.flags()))
                #rospy.loginfo(event.modifiers())
                if event.type() == QtCore.QEvent.MouseButtonDblClick:
                    #rospy.logdebug('meta-double-click')
                    if self._widget.model_selector.selectedIndexes():
                        index = self._widget.model_selector.selectedIndexes()[0]
                        info = self._widget.model_selector.model().fileInfo(index)
                        if ".osim" in info.absoluteFilePath():
                            self.model_path = info.absoluteFilePath()
                            self._widget.model_selected_name.setText(self.model_path)
                            self.update_units()
                            #rospy.logdebug(self.model_path)
                            self.lib_path_exists, self.lib_path = check_if_lib_moment_arm_exists_at_path(self.model_path) 
                            self.update_things()
                        return True
                ## this is not working
                if event.modifiers() == QtCore.Qt.MetaModifier:
                    rospy.logdebug("i am a MetaModifier")
                    if event.type() == QtCore.QEvent.MouseButtonDblClick:
                        rospy.logdebug('meta-double-click')
                        return True
                    if event.type() == QtCore.QEvent.MouseButtonPress:
                        # kill selection when meta-key is also pressed
                        return True
        return super(VioPlugin, self).eventFilter(source, event)


    def shutdown_plugin(self):
        # TODO unregister all publishers here
        self.flexbe_commander_publisher.unregister()
        self.sr.shutdown()
        self.sp.shutdown()
        self.sw.shutdown()

    def save_settings(self, plugin_settings, instance_settings):
        # TODO save intrinsic configuration, usually using:
        # instance_settings.set_value(k, v)
        pass

    def restore_settings(self, plugin_settings, instance_settings):
        # TODO restore intrinsic configuration, usually using:
        # v = instance_settings.value(k)
        pass

    #def trigger_configuration(self):
        # Comment in to signal that the plugin has a way to configure
        # This will enable a setting button (gear icon) in each dock widget title bar
        # Usually used to open a modal configuration dialog
    

    def update_log(self, msg):
        #self._widget.log_box.setText(msg.text)
        # there is the msg.status_code that changes the color of the text here, but i don't know how to format text in QTextEdit element...
        pass 

