RFH.TaskMenu = function (options) {
    "use strict";
    var self = this;
    self.div = $('#'+ options.divId);
    var ros = options.ros;
    self.tasks = {};
    self.activeTask = null;
    self.defaultTaskName = null;

    var statePublisher = new ROSLIB.Topic({
        ros: ros,
        name: '/web_teleop/current_mode',
        messageType: 'std_msgs/String',
        latch: true
    });
    statePublisher.advertise();

    self.addTask = function (taskObject) {
        self.tasks[taskObject.name] = taskObject;
        if (taskObject.showButton) {
       // if (taskObject.buttonText) {
            var checkbox = document.createElement('input');
            checkbox.type = "checkbox";
            checkbox.id = taskObject.buttonText;
            var label = document.createElement('label');
            label.htmlFor = taskObject.buttonText;
            self.div.append(checkbox, label);
            $('#'+taskObject.buttonText).button({label:taskObject.buttonText.replace('_',' ')});
            $('label[for="'+taskObject.buttonText+'"]').addClass(taskObject.buttonClass + ' menu-item').prop('title', taskObject.toolTipText);
            $('#'+taskObject.buttonText).on('click.rfh', 
                                            function(event){
                                                self.buttonCB(taskObject);
                                            });
        }
    };

    self.buttonCB = function (taskObject) {
        var newTask;
        if (taskObject === self.activeTask) {
            newTask = self.defaultTaskName;
        } else {
            newTask = taskObject.name;
        }
        self.stopActiveTask();
        self.startTask(newTask);
    };

    self.startTask = function (taskName) {
        if (self.activeTask !== null) {
            self.stopActiveTask();
        }
        var taskObject = self.tasks[taskName] || self.tasks[self.defaultTaskName];
        taskObject.start();
        if (taskObject.buttonText) {
            $('#'+taskObject.buttonText).prop('checked', true).button('refresh');
        }
        self.activeTask = taskObject;
        statePublisher.publish({'data':taskObject.name});
    };
    
    self.stopActiveTask = function () {
        if (self.activeTask === null) {
            return;
        }
        var taskObject = self.activeTask;
        // Stop currently running task
        taskObject.stop();
        if (taskObject.buttonText) {
            $('#'+taskObject.buttonText).prop('checked', false).button('refresh');
        }
        self.activeTask = null;
    };

    self.removeTask = function (taskObject) {
        self.stopTast(taskObject);
        $('#'+taskObject.buttonText).off('click.rfh');
        self.div.removeChild('#'+taskObject.buttonText);
        self.tasks.pop(self.tasks.indexOf(taskObject));
    };
};

RFH.initTaskMenu = function (divId) {
    RFH.taskMenu = new RFH.TaskMenu({divId: divId,
                                     ros: RFH.ros});
    RFH.taskMenu.addTask(new RFH.Look({ros: RFH.ros, 
                                       div: 'video-main',
                                       head: RFH.pr2.head,
                                       camera: RFH.mjpeg.cameraModel}));
    RFH.taskMenu.defaultTaskName = 'lookingTask';

    RFH.taskMenu.addTask(new RFH.Torso({containerDiv: 'video-main',
                                        sliderDiv: 'torsoSlider',
                                        torso: RFH.pr2.torso}));


    RFH.taskMenu.addTask(new RFH.CartesianEEControl({arm: RFH.pr2.l_arm_cart,
                                                     div: 'video-main',
                                                     gripper: RFH.pr2.l_gripper,
                                                     tfClient: RFH.tfClient,
                                                     camera: RFH.mjpeg.cameraModel}));

    RFH.taskMenu.addTask(new RFH.CartesianEEControl({arm: RFH.pr2.r_arm_cart,
                                                     div: 'video-main',
                                                     gripper: RFH.pr2.r_gripper,
                                                     tfClient: RFH.tfClient,
                                                     camera: RFH.mjpeg.cameraModel}));

    RFH.taskMenu.addTask(new RFH.Drive({ros: RFH.ros, 
                                       targetDiv: 'mjpeg-image',
                                       camera: RFH.mjpeg.cameraModel,
                                       head: RFH.pr2.head,
                                       base: RFH.pr2.base}));
//    RFH.taskMenu.addTask(new RFH.MoveObject({ros:RFH.ros}));
    RFH.taskMenu.addTask(new RFH.PublishLocation({ros:RFH.ros,
                                                  camera: RFH.mjpeg.cameraModel}));
    RFH.taskMenu.addTask(new RFH.ParamLocation({ros:RFH.ros,
                                                name:'paramLocationTask',
                                                paramName:'location',
                                                camera: RFH.mjpeg.cameraModel}));
    RFH.taskMenu.addTask(new RFH.PickAndPlace({ros:RFH.ros,
                                               arm: RFH.pr2.r_arm_cart,
                                               gripper: RFH.pr2.r_gripper}));
    RFH.taskMenu.addTask(new RFH.PickAndPlace({ros:RFH.ros,
                                               arm: RFH.pr2.l_arm_cart,
                                               gripper: RFH.pr2.l_gripper}));
                                    
    // Start looking task by default
    $('#'+RFH.taskMenu.tasks.lookingTask.buttonText).click();
};
