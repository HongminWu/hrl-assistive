RFH.CartesianEEControl = function (options) {
    'use strict';
    var self = this;
    self.arm = options.arm;
    self.side = self.arm.side;
    self.name = options.name || self.side[0]+'EECartTask';
    self.showButton = true;
    var divId = options.div || 'video-main';
    self.buttonText = self.side[0] === 'r' ? 'Right_Hand' : 'Left_Hand';
    self.toolTipText = "Control the %side arm and hand".replace('%side', self.side);
    self.buttonClass = 'hand-button';
    self.$div = $('#'+divId);
    self.gripper = options.gripper;
    self.eeDisplay = options.eeDisplay;
    self.eeDisplay.hide();
    self.preview = false;
    self.handDelta = null;
    self.stepSizes = {'tiny': 0.015,
        'small': 0.04,
        'medium': 0.11,
        'large': 0.25};
    self.tfClient = options.tfClient;
    var ros = self.tfClient.ros;
    self.eeTF = null;
    self.cameraTF = null;
    self.eeInOpMat = null;
    self.op2baseMat = null;
    self.orientRot = 0;
    self.camera = options.camera;
    self.dt = 1000; //hold-repeat time in ms
    self.active = false;
    self.$viewer = $('#viewer-canvas').css('zIndex',1);

    self.pixel23d = new RFH.Pixel23DClient({
        ros: ros,
        cameraInfoTopic: self.camera.infoTopic,
        serviceName: '/pixel_2_3d'
    });

    $('#touchspot-toggle, #toward-button, #away-button').button();
    self.$pickAndPlaceButton = $('.'+self.side[0]+'-arm-ctrl.pick-and-place').button();
    $('#speedOptions-buttons, #'+self.side[0]+'-posrot-set').buttonset();
    $('#touchspot-toggle, #touchspot-toggle-label,#toward-button, #away-button, #armCtrlContainer').hide();
    $('#armCtrlContainer').css('zIndex',5);
    $('#ctrl-ring .center').on('mousedown.rfh', function (e) {e.stopPropagation(); });


    var cameraSwing = function (event) {
        // Clear the canvas, turn on pointcloud visibility...
        if (RFH.kinectHeadPointCloud.locked) {
            return; 
        } else {
            RFH.kinectHeadPointCloud.locked = true;
        }
        var restoreArmContainer = $('#armCtrlContainer').is(':visible') ? true : false
        $('#armCtrlContainer').hide();
        self.gripperDisplay.hide();
        self.eeDisplay.show();
        RFH.kinectHeadPointCloud.setVisible(true);
        RFH.viewer.renderer.setClearColor(0x666666,0.5);
        //$('#mjpeg-image').css('visibility','hidden');
        // Swing the camera to view pointcloud from the side
        var camTF = self.cameraTF.clone();
        var camQuat = new THREE.Quaternion().copy(camTF.rotation);
        var camPos = new THREE.Vector3().copy(camTF.translation);
        var camMat = new THREE.Matrix4().makeRotationFromQuaternion(camQuat).setPosition(camPos);

        var eeTF = self.eeTF.clone();
        var eeQuat = new THREE.Quaternion().copy(eeTF.rotation);
        var eePos = new THREE.Vector3().copy(eeTF.translation);
        var eeMat = new THREE.Matrix4().makeRotationFromQuaternion(eeQuat).setPosition(eePos); 

        var arcRadius = new THREE.Vector3().subVectors(camPos,eePos).length();
        if (self.side == 'right') { // Swing the camera left with the right arm, and vice versa
            var goalDir = new THREE.Vector3(arcRadius,0,0);
        } else {
            var goalDir = new THREE.Vector3(-arcRadius,0,0);
        }

        var goalInCam = goalDir.applyMatrix4(camMat); // Get offset direction relative to camera in base frame
        var goalFromCam = goalInCam.sub(camPos); // Get vector from cameraPos to goalPos in cam frame
        //var goalVec = new THREE.Vector3().addVectors(eePos, goalFromCam); // Apply same offset at hand 
        var goalVec = new THREE.Vector3(0,0,eePos.z);
        var linearMidpoint = new THREE.Vector3().lerpVectors(goalVec, camPos, 0.5);
        var centerToMidpoint = new THREE.Vector3().subVectors(linearMidpoint, eePos);
        centerToMidpoint.setLength(0.707100678 * arcRadius);
        var arcMidpoint = new THREE.Vector3().addVectors(eePos, centerToMidpoint);
        var arcSpline = new THREE.CatmullRomCurve3([camPos, arcMidpoint, goalVec]);
        var arcPoints = arcSpline.getPoints(60);

        // Clean up and get back to business as usual
        var cleanup3DView = function () {
            RFH.viewer.renderer.setClearColor(0x000000,0);
            RFH.kinectHeadPointCloud.setVisible(false);
            $('#mjpeg-image').css('visibility','visible');
            if (restoreArmContainer) { $('#armCtrlContainer').show(); }
            RFH.kinectHeadPointCloud.locked = false;
            self.gripperDisplay.show();
            self.eeDisplay.hide();
        }

        // All the points defined, move the camera and render views
        var camera = RFH.viewer.camera;
        var reverse = false;
        var peakPauseMS = 2800; // Default: 1500
        var travelTimeMS = 400; // Default: 300
        var delay = travelTimeMS / arcPoints.length;
        // Set camera position along path, adjust lookAt, render, and set next call after delay
        var renderCameraStep = function (step) {
            var pt = arcPoints[step];
            camera.position.set(pt.x, pt.y, pt.z);
            camera.lookAt(eePos);
            RFH.viewer.renderer.render(RFH.viewer.scene, camera);
            if (!reverse) { // Still going out to goal point
                if (step < arcPoints.length-1) {
                    setTimeout(renderCameraStep, delay, step+1);
                } else {
                    reverse = true;
                    setTimeout(renderCameraStep, peakPauseMS, step-1); // Linger at the furthest point
                }
            } else { // Bringing view back to head perspective
                step <= 1 ? cleanup3DView() : setTimeout(renderCameraStep, delay, step-1);  // Clean up once done
            }
        }
        renderCameraStep(0); // Kick off with initial call
    };
    $('.camera-swing.'+self.side[0]+'-arm-ctrl').button().on('click.rfh', cameraSwing);


    self.getStepSize = function () {
        return $('input[name=speedOption]:checked').attr('id');
    };

    var updatePickPlaceButton = function (graspingMsg) {
        if (graspingMsg.data) {
            self.$pickAndPlaceButton.text("Set Down");
            self.$pickAndPlaceButton.prop('title', 'Guided process for placing the currently held object');
     //       self.$pickAndPlaceButton.off('click.pickandplace').on('click.pickandplace', function(){RFH.taskMenu.tasks['place'].sendTaskGoal(self.side)});
        } else {
            self.$pickAndPlaceButton.text("Move Object");
            self.$pickAndPlaceButton.prop('title', 'Guided process for picking up and moving an object');
    //        self.$pickAndPlaceButton.off('click.pickandplace').on('click.pickandplace', function(){RFH.taskMenu.tasks['pick'].sendTaskGoal(self.side)});
        }
    };
    self.gripper.graspingCBList.push(updatePickPlaceButton);
    self.$pickAndPlaceButton.on('click.pickandplace', function(){RFH.taskMenu.tasks['pick_and_place'].sendTaskGoal(self.side)});

    self.getPoseFromDelta = function (xyzrpy) {
        // Get default values for unspecified options
        var x = xyzrpy.x || 0.0;
        var y = xyzrpy.y || 0.0;
        var z = xyzrpy.z || 0.0;
        var roll = xyzrpy.roll || 0.0;
        var pitch = xyzrpy.pitch || 0.0;
        var yaw = xyzrpy.yaw || 0.0;
        var posStep = self.stepSizes[self.getStepSize()];
        var rotStep = self.rotationControl.stepSizes[self.getStepSize()];
        var handAng, clickAng, goalAng;
        var dx, dy, dz, dRoll, dPitch, dYaw;

        if (self.eeTF === null) {
            console.warn("Hand Data not available to send commands.");
            return;
        }
        handAng = Math.atan2(self.eeTF.translation.y, self.eeTF.translation.x);
        clickAng = Math.atan2(y,x) - Math.PI/2;
        goalAng = handAng + clickAng;
        dx = (x === 0.0) ? 0.0 : posStep * Math.cos(goalAng);
        dy = (y === 0.0) ? 0.0 : posStep * Math.sin(goalAng);
        dz = posStep * z;
        dRoll = rotStep * roll;
        dPitch = rotStep * pitch;
        dYaw = rotStep * yaw;
        // Convert del goal to Matrix4
        var cmdDelPos = new THREE.Vector3(posStep*x, -posStep*y, posStep*z);
        var cmdDelRot = new THREE.Euler(-rotStep*roll, -rotStep*pitch, rotStep*yaw);
        var cmd = new THREE.Matrix4().makeRotationFromEuler(cmdDelRot);
        cmd.setPosition(cmdDelPos);
        // Get EE transform in THREE mat4
        var eeQuat = new THREE.Quaternion(self.eeTF.rotation.x,
                                         self.eeTF.rotation.y,
                                         self.eeTF.rotation.z,
                                         self.eeTF.rotation.w);
        var eeMat = new THREE.Matrix4().makeRotationFromQuaternion(eeQuat);
        // Transform del goal (in hand frame) to base frame
        cmd.multiplyMatrices(eeMat, cmd);
        var pos = new THREE.Vector3();
        var quat = new THREE.Quaternion();
        var scale = new THREE.Vector3();
        cmd.decompose(pos, quat, scale);
        pos.x += dx;
        pos.y += dy;
        pos.z += dz;

        var frame = self.tfClient.fixedFrame;
        var pos = {x: self.eeTF.translation.x + dx,
                   y: self.eeTF.translation.y + dy,
                   z: self.eeTF.translation.z - dz};
        quat = new ROSLIB.Quaternion({x:quat.x, y:quat.y, z:quat.z, w:quat.w});
        return {position: pos,
                orientation: quat,
                frame_id: frame};

    };

    self.eeDeltaCmd = function (xyzrpy) {
        var goal = self.getPoseFromDelta(xyzrpy);
        self.arm.sendPoseGoal(goal);
    };

    /// GRIPPER SLIDER CONTROLS ///
    var gripperZeroOffset = self.side[0] == 'r' ? -0.00063 : 0.0013;
    self.gripperDisplay = new RFH.GripperDisplay({gripper: self.gripper,
                                                  zeroOffset: gripperZeroOffset,
                                                  divId: self.side[0] +'GripperCtrlContainer'});

    self.updateCtrlRingViz = function () {
        // Check that we have values for both camera and ee frames
        if (!self.active) { return; }
        if (self.eeTF === null || self.cameraTF === null) { 
            console.log("Cannot update hand control ring, missing tf information");
            return;
        }
        var eePos =  self.eeTF.translation.clone(); // 3D Hand position in /base_link
        var camPos = self.cameraTF.translation.clone(); // 3D camera position in /base_link
        var transformStr;

        var camQuat = self.cameraTF.rotation.clone();
        camQuat = new THREE.Quaternion(camQuat.x, camQuat.y, camQuat.z, camQuat.w);
        camQuat.multiply(new THREE.Quaternion(0.5, -0.5, 0.5, 0.5));//Rotate from optical frame to link
        var camEuler = new THREE.Euler().setFromQuaternion(camQuat, 'ZYX');// NO IDEA, but it works with this order...
        var rot = camEuler.z;//Rotation around Z -- counter rotate icon to keep arrow pointed forward.
        var dx = eePos.x - camPos.x;
        var dy = eePos.y - camPos.y;
        var dz = eePos.z - camPos.z;
        var dxy = Math.sqrt(dx*dx + dy*dy);
        var phi = Math.atan2(dxy, dz) - Math.PI/2; // Angle from horizontal
        var rotX = phi - Math.PI/2;
        transformStr = "rotateX("+rotX.toString()+"rad) rotate("+rot.toString()+"rad)";

        var rect = $('#armCtrlContainer')[0].getBoundingClientRect();
        var videoHeight = $('#armCtrlContainer').parent().height();
        var videoWidth = $('#armCtrlContainer').parent().width();
        var ratio = Math.max(rect.height/videoHeight, rect.width/videoWidth);
        $('#armCtrlContainer').css({'transform':transformStr});
    };

    self.updateOpFrame = function () {
        // Define an 'operational frame' at the end effector (ee) aligned with the perspective of the camera
        // (i.e. z-axis along line from camera center through ee center for z-out optical frames,
        //  x- and y-axes rotated accordingly.  Commands will be issued in this frame, so they have the exact
        // effect that it looks like they should from the flat, 2D camera view at all times.

        // Check that we have values for both camera and ee frames
        if (self.eeTF === null || self.cameraTF === null) { return; }
        // Format ee frame as transformation matrix
        var eePosInBase = new THREE.Vector3().copy(self.eeTF.translation);
        var eeQuatInBase = new THREE.Quaternion(self.eeTF.rotation.x,
                self.eeTF.rotation.y,
                self.eeTF.rotation.z,
                self.eeTF.rotation.w);
        var eeInBase = new THREE.Matrix4();
        eeInBase.makeRotationFromQuaternion(eeQuatInBase);
        eeInBase.setPosition(eePosInBase);

        // Format camera frame as transformation matrix
        var camPosInBase = new THREE.Vector3().copy(self.cameraTF.translation);
        var camQuatInBase = new THREE.Quaternion(self.cameraTF.rotation.x,
                self.cameraTF.rotation.y,
                self.cameraTF.rotation.z,
                self.cameraTF.rotation.w);
        var camInBase = new THREE.Matrix4();
        camInBase.makeRotationFromQuaternion(camQuatInBase);
        camInBase.setPosition(camPosInBase);

        // Get ee position in camera frame
        var base2Cam = new THREE.Matrix4().getInverse(camInBase);
        var eePosInCam = eePosInBase.clone().applyMatrix4(base2Cam);

        // Get operational frame (op) in camera frame
        var delAngX = -Math.atan2(eePosInCam.y, eePosInCam.z);
        var delAngY = Math.atan2(eePosInCam.x, eePosInCam.z);
        var delAngEuler = new THREE.Euler(delAngX, delAngY, 0);
        var opInCamMat = new THREE.Matrix4();
        opInCamMat.makeRotationFromEuler(delAngEuler);
        opInCamMat.setPosition(eePosInCam);

        // Get EE pose in operational frame
        var eeInOpMat = new THREE.Matrix4().multiplyMatrices(base2Cam, eeInBase.clone()); // eeInOpMat is ee in cam frame
        var cam2Op = new THREE.Matrix4().getInverse(opInCamMat);
        eeInOpMat.multiplyMatrices(cam2Op, eeInOpMat); // eeInOpMat is ee in Operational Frame
        self.eeInOpMat = eeInOpMat.clone(); //Only store accessible to other functions once fully formed
        self.op2baseMat = new THREE.Matrix4().multiplyMatrices(camInBase, opInCamMat);

        // Receive Command Here, apply to current ee in op frame
        var cmdDelPos = new THREE.Vector3(0,0,0);
        var cmdDelRot = new THREE.Euler(0,0,0.5*Math.PI);
        var cmd = new THREE.Matrix4().makeRotationFromEuler(cmdDelRot);
        cmd.setPosition(cmdDelPos);
        var goalInOpMat = new THREE.Matrix4().multiplyMatrices(cmd, self.eeInOpMat.clone());
        //Transform goal back to base frame
        goalInOpMat.multiplyMatrices(self.op2baseMat, goalInOpMat);
    };

    self.updatePreview = function () {
        // preview gripper pose = handPose + offset
        if (!self.preview) {return;};
        if (self.handDelta === null) {return;};
        var pose = self.getPoseFromDelta(self.handDelta);
        self.eeDisplay.setCurrentPose(pose);
    };

    var updateHandDelta = function (e) {
        switch(e.target.id) {
            case 'ctrl-ring':
                self.handDelta = getDeltaFromEvent(e);
                break;
            case 'away-button':
                self.handDelta = {z: 1};
                break;
            case 'toward-button':
                self.handDelta = {z: -1};
                break;
        }
    };

    self.startPreview = function () {
        self.preview = true;
        self.eeDisplay.showCurrent();
    };

    self.stopPreview = function () {
        self.preview = false;
        self.eeDisplay.hideCurrent();
        self.handDelta = null;
    };

    // Get EE frame updates from TF
    if (self.arm.ee_frame !== '') {
        self.tfClient.subscribe(self.arm.ee_frame, function (tf) {
            self.eeTF = tf;
            self.updateOpFrame();
            self.updatePreview();
            self.updateCtrlRingViz();
        });
        console.log("Subscribing to TF Frame: "+self.arm.ee_frame);
    } else {
        console.log("Empty EE Frame for " + self.arm.side + " arm.");
    }

    // Get camera frame updates from TF
    self.checkCameraTF = function () {
        if (self.camera.frame_id !== '') {
            self.tfClient.subscribe(self.camera.frame_id, function (tf) {
                self.cameraTF = tf;
                self.updateOpFrame();
                self.updateCtrlRingViz();
            }
            );
        } else {
            setTimeout(self.checkCameraTF, 500);
        }
    };
    self.checkCameraTF();

    self.checkMouseButtonDecorator = function (f) {
        return function (e) {
            if (e.which === 1) {
                f(e);
            } else {
                e.stopPropagation();
                return;
            }
        };
    };

    self.ctrlRingActivate = self.checkMouseButtonDecorator(function (e) {
        $('#ctrl-ring, #ctrl-ring > .arrow').removeClass('default').addClass('active');
        var xyzrpy = getDeltaFromEvent(e);
        var ringMove = function (dX, dY) {
            if ( !$('#ctrl-ring').hasClass('active') ) { return; }
            self.eeDeltaCmd({x: dX, y: dY});
            setTimeout(function() {ringMove(dX, dY);} , self.dt);
        };
        ringMove(xyzrpy.x, xyzrpy.y);
    });

    var getDeltaFromEvent = function (e) {
        var pt = RFH.positionInElement(e);
        var w = $(e.target).width();
        var h = $(e.target).height();
        var ang = Math.atan2(-(pt[1]-h/2)/h, (pt[0]-w/2)/w);
        var delX = Math.cos(ang);
        var delY = Math.sin(ang);
        return {x: delX, y: delY};
    };

    self.ctrlRingActivateRot = self.checkMouseButtonDecorator(function (e) {
        $('#ctrl-ring').removeClass('default').addClass('active');
        var pt = RFH.positionInElement(e);
        var w = $(e.target).width();
        var h = $(e.target).height();
        var delX = (pt[0]-w/2)/w;
        var delY = -(pt[1]-w/2)/h;
        var ringMove = function (dX, dY) {
            if ( !$('#ctrl-ring').hasClass('active') ){ return; }
            self.eeDeltaCmd({roll: delY, pitch: delX});
            setTimeout(function() {ringMove(dX, dY);} , self.dt);
        };
        ringMove(delX, delY);
    });

    self.inactivate = function (e) {
        $(e.target).removeClass('active').addClass('default');
    };

    self.awayCB = self.checkMouseButtonDecorator(function (e) {
        $(e.target).removeClass('default').addClass('active');
        var moveCB = function() {
            if ( !$('#away-button').hasClass('active') ) {return;}
            self.eeDeltaCmd({z: 1});
            setTimeout(moveCB, self.dt);
        };
        moveCB();
    });

    self.towardCB = self.checkMouseButtonDecorator(function (e) {
        $(e.target).removeClass('default').addClass('active');
        var moveCB = function() {
            if ( !$('#toward-button').hasClass('active') ) {return;}
            self.eeDeltaCmd({z: -1});
            setTimeout(moveCB, self.dt);
        };
        moveCB();
    });

    self.cwCB = self.checkMouseButtonDecorator(function (e) {
        $(e.target).removeClass('default').addClass('active');
        var moveCB = function() {
            if ( !$('#away-button').hasClass('active') ) {return;}
            self.eeDeltaCmd({yaw: 1});
            setTimeout(moveCB, self.dt);
        };
        moveCB();
    });

    self.ccwCB = self.checkMouseButtonDecorator(function (e) {
        $(e.target).removeClass('default').addClass('active');
        var moveCB = function() {
            if ( !$('#toward-button').hasClass('active') ) {return;}
            self.eeDeltaCmd({yaw: -1});
            setTimeout(moveCB, self.dt);
        };
        moveCB();
    });

    /// TRACK HAND WITH CAMERA ///
    self.trackHand = function (doTrack) {
        if (doTrack) {
            RFH.pr2.head.trackPoint(0, 0, 0, self.side[0]+'_gripper_tool_frame');
        } else {
            RFH.pr2.head.stopTracking();
        }
    };

/*    var trajectoryCB = function (msg) { // Define CB for received trajectory from planner
        if (msg.robot_trajectory.joint_trajectory.points.length === 0) {
            console.log("Empty Trajectory Received.");
        } else {
            console.log("Got Trajectory", msg);
            self.arm.sendTrajectoryGoal(msg.robot_trajectory.joint_trajectory);
        }
        // Clean up interface once everything is done...
        unsetTouchSpot();
    };

    var touchspotClickCB = function (e) { 
        var onRetCB = function (pose_stamped) { // Define callback for response to pixel-2-3D from click
            var pose = pose_stamped.pose;
            var quat = new THREE.Quaternion(pose.orientation.x,
                                            pose.orientation.y,
                                            pose.orientation.z,
                                            pose.orientation.w);
            var poseRotMat = new THREE.Matrix4().makeRotationFromQuaternion(quat);
            var offset = new THREE.Vector3(0.18, 0, 0); //Get to x dist from point along normal
            offset.applyMatrix4(poseRotMat);
            var desRotMat = new THREE.Matrix4().makeRotationFromEuler(new THREE.Euler(0, Math.PI, 0));
            poseRotMat.multiply(desRotMat);
            poseRotMat.setPosition(new THREE.Vector3(pose.position.x + offset.x,
                                                     pose.position.y + offset.y,
                                                     pose.position.z + offset.z));
            var trans = new THREE.Matrix4();
            var scale = new THREE.Vector3();
            poseRotMat.decompose(trans, quat, scale);

            self.arm.planTrajectory({
                position: new ROSLIB.Vector3({x:trans.x, y:trans.y, z:trans.z}),
                orientation: new ROSLIB.Quaternion({x:quat.x, y:quat.y, z:quat.z, w:quat.w}),
                frame_id: 'base_link',
                cb: trajectoryCB
            });
        };

        var pt = RFH.positionInElement(e);
        var x = pt[0]/$(e.target).width();
        var y = pt[1]/$(e.target).height();
        self.pixel23d.callRelativeScale(x, y, onRetCB);
    };

    var setTouchSpot = function () {
            $('#armCtrlContainer').hide();
            self.trackHand(false);
            $('.map-look').addClass('visible').show();
            self.$div.addClass('cursor-select');
    };

    var unsetTouchSpot = function () {
            self.$div.off('click.touchspot');
            $('.map-look').removeClass('visible').hide();
            self.$div.removeClass('cursor-select');
            $('#touchspot-toggle').prop('checked', false).button("refresh");
            self.setPositionCtrls();
            self.trackHand(true);
    };

    self.touchSpotCB = function (e) {
        if ($('#touchspot-toggle').prop('checked')) {
            unsetTouchSpot();
        } else {
            setTouchSpot();
            self.$div.one('click.touchspot', touchspotClickCB);
        }
    };
*/

    self.setRotationCtrls = function (e) {
        $('#armCtrlContainer').hide();
        self.rotationControl.setActive(true);
        $(window).resize(); // Trigger canvas to update size
    };

    self.setPositionCtrls = function (e) {
        // self.$viewer.hide();
        self.rotationControl.setActive(false);
        $('#armCtrlContainer').show();
        $('#ctrl-ring, #away-button, #toward-button').on('mouseup.rfh', self.inactivate)
                                                     .on('mouseout.rfh mouseleave.rfh blur.rfh', function(e){ self.inactivate(e);
                                                                                                              self.stopPreview(); })
                                                     .on('mouseenter.rfh mouseover.rfh', self.startPreview )
                                                     .on('mousemove.rfh', function (e) {updateHandDelta(e);
                                                                                        self.updatePreview()})
                                                    
        $('#ctrl-ring').on('mousedown.rfh', self.ctrlRingActivate);
        $('#away-button').on('mousedown.rfh', self.awayCB);
        $('#toward-button').on('mousedown.rfh', self.towardCB);
    };

    self.rotationControl = new RFH.EERotation({'tfClient': self.tfClient,
                                               'arm':self.arm,
                                               'eeDeltaCmdFn': self.eeDeltaCmd,
                                               'updatePreviewFn': self.updatePreview,
                                               'startPreviewFn': self.startPreview,
                                               'stopPreviewFn': self.stopPreview,
                                               'previewDelta': self.handDelta});

    $('#'+self.side[0]+'-posrot-pos').on('click.rfh', self.setPositionCtrls);
    $('#'+self.side[0]+'-posrot-rot').on('click.rfh', self.setRotationCtrls);
    $('label[for='+self.side[0]+'-posrot-pos').prop('title', "Adjust the position of the fingertips");
    $('label[for='+self.side[0]+'-posrot-rot').prop('title', "Adjust the rotation of hand,\nrotating about the fingertips");
    $("#ctrl-ring").prop('title', 'Move hand in any direction, parallel to the floor');
    $("#away-button").prop('title', 'Move hand straight down');
    $("#toward-button").prop('title', 'Move hand straight up');


    /// TASK START/STOP ROUTINES ///
    self.start = function () {
        self.trackHand(true);
        $('.'+self.side[0]+'-arm-ctrl, .arm-ctrl').show();
        $('#armCtrlContainer, #away-button, #toward-button').show();
        $('#speedOptions').show();
        self.gripperDisplay.show();
        $('#'+self.side[0]+'-posrot-set').show();
        $('#'+self.side[0]+'-posrot-pos').click();
        self.active = true;
        self.$viewer.show();
        self.updateCtrlRingViz();
    };

    self.stop = function () {
        $('.'+self.side[0]+'-arm-ctrl, .arm-ctrl').hide();
        $('#armCtrlContainer').hide();
        $('#away-button, #toward-button').off('mousedown.rfh mouseenter.rfh mouseover.rfh mousemove.rfh').hide();
        $('#ctrl-ring').off('mouseup.rfh mouseout.rfh mouseleave.rfh blur.rfh mousedown.rfh mouseenter.rfh mouseover.rfh mousemove.rfh');
        self.$viewer.hide();
        $('#speedOptions').hide();
        self.gripperDisplay.hide();
        self.eeDisplay.hide();
        if ($('#touchspot-toggle').prop('checked')) {
            $('#touchspot-toggle-label').click();
        }
        $('#touchspot-toggle-label').off('click.rfh').hide();
        self.trackHand(false);
        self.active = false;
        self.rotationControl.hide();
//        for (var dir in self.rotArrows) {
//            self.rotArrows[dir].mesh.visible = false;
//            self.rotArrows[dir].edges.visible = false;
//        }
    };
};
