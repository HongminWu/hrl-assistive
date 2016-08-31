var RFH = (function (module) {
    module.TaskMenu = function (options) {
        "use strict";
        var self = this;
        self.div = $('#'+ options.divId);
        var ros = options.ros;
        self.domains = {};

        var startButtonCB = function (event) {
            // Determine currently selected domain from domain-select box
            // Maybe parse other select boxes for options to pass? Or leave this to the start method in the domain?
            // Call start method from currently selected domain
        };

        var updateOptions = function (event) {
            // Update to show/hide appropriate option select boxes when domain is changed
            var domain = $('#domain-select:selected').val();
            $('#task-menu select.option-select').hide();
            $('#task-menu select.option-select.option-'+domain).show();
        };

        $('#domain-select').on('change', updateOptions);
    };

    module.initTaskMenu = function () {
        RFH.taskMenu = new RFH.TaskMenu({divId: 'task-menu',
                                         ros: RFH.ros});
        $('#task-select').selectmenu({collapsible:true});
        $('.task-option-select').selectmenu();

        RFH.taskMenu.domains.pick = new RFH.Domains.Pick({ros:RFH.ros,
                                                          r_arm: RFH.pr2.r_arm_cart,
                                                          r_gripper: RFH.pr2.r_gripper,
                                                          l_arm: RFH.pr2.l_arm_cart,
                                                          l_gripper: RFH.pr2.l_gripper});

        RFH.taskMenu.domains.place = new RFH.Domains.Place({ros:RFH.ros,
                                                    r_arm: RFH.pr2.r_arm_cart,
                                                    r_gripper: RFH.pr2.r_gripper,
                                                    l_arm: RFH.pr2.l_arm_cart,
                                                    l_gripper: RFH.pr2.l_gripper});
        RFH.taskMenu.domains.pick_and_place = new RFH.Domains.PickAndPlace({ros:RFH.ros});
        RFH.taskMenu.domains.realtime_base_selection = new RFH.Domains.RealtimeBaseSelection({ros:RFH.ros});
        RFH.taskMenu.domains.adl = Domains.ADL({ros:RFH.ros});
    };
    return module;
})(RFH || {});
