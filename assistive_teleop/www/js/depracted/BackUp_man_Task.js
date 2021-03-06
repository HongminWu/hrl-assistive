var ManipulationTask = function (ros) {
    'use strict';
    var manTask = this;
    manTask.ros = ros;
    //Topic used in manTask
    manTask.USER_INPUT_TOPIC = "manipulation_task/user_input";
    manTask.USER_FEEDBACK_TOPIC = "manipulation_task/user_feedback";
    manTask.EMERGENCY_TOPIC = "manipulation_task/emergency";
    manTask.STATUS_TOPIC = "manipulation_task/status";
    //status_topic
    manTask.statusPub = new manTask.ros.Topic({
        name: manTask.STATUS_TOPIC,
        messageType: 'std_msgs/String'
    });
    manTask.statusPub.advertise();
    manTask.scoop = function () {
        var msg = new manTask.ros.Message({
          data: 'Scooping'
        });
        assistive_teleop.log('Please, follow the step 2 to select the action.');
        manTask.statusPub.publish(msg);
    };

    manTask.feed = function () {
        var msg = new manTask.ros.Message({
          data: 'Feeding'
        });
        assistive_teleop.log('Please, follow the step 2 to select the action.');
        manTask.statusPub.publish(msg);
    };

    manTask.both = function () {
        var msg = new manTask.ros.Message({
          data: 'Both'
        });
        assistive_teleop.log('Please, follow the step 2 to select the action.');
        manTask.statusPub.publish(msg);
    };


    //Publisher used for start, stop, and continue
    manTask.userInputPub = new manTask.ros.Topic({
        name: manTask.USER_INPUT_TOPIC,
        messageType: 'std_msgs/String'
    });
    manTask.userInputPub.advertise();

    manTask.emergencyPub = new manTask.ros.Topic({
        name: manTask.EMERGENCY_TOPIC,
        messageType: 'std_msgs/String'
    });
    manTask.emergencyPub.advertise();

    manTask.userFeedbackPub = new manTask.ros.Topic({
        name: manTask.USER_FEEDBACK_TOPIC,
        messageType: 'std_msgs/String'
    });
    manTask.userFeedbackPub.advertise();
    // Function for start, stop, and continue
    manTask.start = function () {
        var msg = new manTask.ros.Message({
          data: 'Start'
        });
        manTask.userInputPub.publish(msg);
        assistive_teleop.log('Starting the manipulation task');
        assistive_teleop.log('Please, follow the step 3 when "Requesting Feedback" message shows up.');
        console.log('Publishing Start msg to manTask system.');
    };

    manTask.stop = function () {
        var msg = new manTask.ros.Message({
          data: 'STOP'
        });
        manTask.emergencyPub.publish(msg);
        assistive_teleop.log('Stopping the manipulation task');
        assistive_teleop.log('Please, press "Continue" to re-start the action. Or re-start from step 1.');
        console.log('Publishing Stop msg to manTask system.');
    };

    manTask.continue_ = function () {
        var msg = new manTask.ros.Message({
          data: 'Continue'
        });
        manTask.userInputPub.publish(msg);
        assistive_teleop.log('Continuing the manipulation task');
        assistive_teleop.log('Please, follow the step 3 when "Requesting Feedback" message shows up.');
        console.log('Publishing Continue msg to manTask system.');
    };
    // Function to report the feedback
    manTask.success = function () {
        var msg = new manTask.ros.Message({
          data: 'SUCCESS'
        });
        manTask.userFeedbackPub.publish(msg);
        assistive_teleop.log('Successful run');
        console.log('Reporting the feedback message.');
    };

    manTask.failure = function () {
        var msg = new manTask.ros.Message({
          data: 'FAIL'
        });
        manTask.userFeedbackPub.publish(msg);
        assistive_teleop.log('Failed run');
        console.log('Reporting the feedback message.');
    };


    //part added.
    manTask.feedbackSub = new manTask.ros.Topic({
        name: 'manipulation_task/feedbackRequest',
        messageType: 'std_msgs/String'});
    manTask.feedbackSub.subscribe(function (msg) {
        assistive_teleop.log(msg.data);
    });


};

var initManTaskTab = function() {
  assistive_teleop.manTask = new ManipulationTask(assistive_teleop.ros);
  assistive_teleop.log('initiating manipulation Task');

    $('#man_task_Scooping').click(function(){assistive_teleop.manTask.scoop();});
    $('#man_task_Feeding').click(function(){assistive_teleop.manTask.feed();});
    $('#man_task_Both').click(function(){assistive_teleop.manTask.both();});
    $('#man_task_start').click(function(){assistive_teleop.manTask.start();});
    $('#man_task_stop').click(function(){assistive_teleop.manTask.stop();});
    $('#man_task_Continue').click(function(){assistive_teleop.manTask.continue_();});
    $('#man_task_success').click(function(){assistive_teleop.manTask.success();});
    $('#man_task_Fail').click(function(){assistive_teleop.manTask.failure();});

}
