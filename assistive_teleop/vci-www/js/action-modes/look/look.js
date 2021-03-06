var RFH = (function (module) {
    module.Look = function (options) {
        'use strict';
        var self = this;
        self.name = options.name || 'lookingAction';
        self.buttonID = options.buttonID || 'look-mode-button';
        var ros = options.ros;
        self.showButton = true;
        self.toolTipText = "Move the head to look around";
        var imageDivId = options.imageDivId || 'mjpeg-image';
        var $imageDiv = $("#" + imageDivId);
        var $mapLookDivs = $('.map-look');
        var camera = options.camera || new RFH.ROSCameraModel();
        var head = options.head || new Pr2Head(ros);
        var zoomLevel = 1.0;
        var maxZoom = 4;
        var zoomServiceClient = new ROSLIB.Service({
            ros: ros,
            name: '/set_cropdecimate',
            serviceType: 'assistive_teleop/SetCropDecimateParams'
        });

        var hfov = 1;
        var vfov = 0.75; //FOV of kinect is ~1 radians wide, 0.75 radians tall
        var SCALE = 0.8; //Scale large motions so we don't over shoot
        var edgeLook = function (event) {
            var dx = 0, dy = 0;
            var classes = event.target.classList;
            if (classes.contains("top")) { dy = -SCALE  * vfov/zoomLevel; }
            if (classes.contains("bottom")) { dy = SCALE  * vfov/zoomLevel; }
            if (classes.contains("left")) { dx = SCALE * hfov/zoomLevel; }
            if (classes.contains("right")) { dx = -SCALE * hfov/zoomLevel; }
            head.delPosition(dx, dy); 
            event.stopPropagation();
        };
        $mapLookDivs.on('click.rfh-look', edgeLook);

        var pointHead = function (e) {
            var pt = RFH.positionInElement(e); 
            var pctOffset = (50 - (50/zoomLevel))/100;
            var px = ((pt[0]/e.target.clientWidth)/zoomLevel + pctOffset) * camera.width;
            var py = ((pt[1]/e.target.clientHeight)/zoomLevel + pctOffset) * camera.height;
            var xyz =  camera.projectPixel(px, py);
            head.pointHead(xyz[0], xyz[1], xyz[2], camera.frame_id);
        };

        var $zoomInButton = $('#controls > .zoom.in').button().on('click.rfh', function(e){self.setZoom(zoomLevel*2);});
        var $zoomOutButton = $('#controls > .zoom.out').button().on('click.rfh', function(e){self.setZoom(zoomLevel*0.5);}).button('disable');

        self.setZoom = function (newZoomLevel) {
            $zoomOutButton.button('enable');
            $zoomInButton.button('enable');
            if (newZoomLevel <= 1) {
                newZoomLevel = 1;
                $zoomOutButton.button('disable');
            }
            if (newZoomLevel >= maxZoom) {
                newZoomLevel = maxZoom;
                $zoomInButton.button('disable');
            }
            zoomLevel = newZoomLevel; 
            $imageDiv.css({transform:'scale('+zoomLevel+')'});
        };

        self.start = function () {
            $imageDiv.addClass("cursor-eyes").on("click.rfh-look", pointHead);
            $mapLookDivs.show();
            $('.zoom').show();
        };

        self.stop = function () {
            self.setZoom(1);
            $imageDiv.removeClass("cursor-eyes").off("click.rfh-look");
            $mapLookDivs.hide();
            $('.zoom').hide();
        };
    };
    return module;
})(RFH || {});
