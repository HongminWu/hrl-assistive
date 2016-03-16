RFH.EERotation = function (options) {
    'use strict';
    var self = this;
    self.arm = options.arm;
    self.tfClient = options.tfClient;
    self.eeDeltaCmd = options.eeDeltaCmdFn;
    self.$viewer = $('#viewer-canvas');
    self.raycaster = new THREE.Raycaster();
    self.hoveredMesh = null;
    self.clickedMesh = null;

    if (self.arm.ee_frame !== '') {
        self.tfClient.subscribe(self.arm.ee_frame, function (tf) {
            self.eeTF = tf;
            self.updateRotImage();
        });
        console.log("Subscribing to TF Frame: "+self.arm.ee_frame);
    } else {
        console.log("Empty EE Frame for " + self.arm.side + " arm.");
    }

    self.hide = function() {
        for (var dir in self.rotArrows) {
            self.rotArrows[dir].mesh.visible = false;
            self.rotArrows[dir].edges.visible = false;
        }
    };

    self.show = function() {
        for (var dir in self.rotArrows) {
            self.rotArrows[dir].mesh.visible = true;
            self.rotArrows[dir].edges.visible = true;
        }
    };

    self.setActive = function (bool) {
        if (bool) {
            self.$viewer.on('click.rot-ctrl', self.canvasClickCB);
            self.$viewer.on('mousedown.rot-ctrl', self.canvasMousedownCB);
            self.$viewer.on('mouseup.rot-ctrl', self.canvasMouseupCB);
            self.$viewer.on('mousemove.rot-ctrl', self.canvasMouseMoveCB);
            self.show();
        } else {
            self.$viewer.off('click.rot-ctrl');
            self.$viewer.off('mousedown.rot-ctrl');
            self.$viewer.off('mouseup.rot-ctrl');
            self.$viewer.off('mousemove.rot-ctrl');
            self.hide();

        }
    };

    self.stepSizes = {'tiny': Math.PI/16,
        'small': Math.PI/8,
        'medium': Math.PI/6,
        'large': Math.PI/4};

    self.getMeshPointedAt = function (event) {
        var mouse = new THREE.Vector2();
        var pt = RFH.positionInElement(event);
        var canvas = RFH.viewer.renderer.getContext().canvas; 
        mouse.x = 2 * (pt[0] - canvas.width / 2) / canvas.width;
        mouse.y = -2 * (pt[1] - canvas.height / 2) / canvas.height;

        self.raycaster.setFromCamera(mouse, RFH.viewer.camera);
        var objs = self.raycaster.intersectObjects( RFH.viewer.scene.children, true );
        if (objs.length > 0 && objs[0].object instanceof THREE.Mesh && objs[0].object.userData.side === self.side) {
            return self.rotArrows[objs[0].object.userData.direction];
        } else {
            return null;
        }
    };

    self.canvasClickCB = function (event) {
        var clickedMesh = self.getMeshPointedAt(event);
        if (clickedMesh !== null) {
            self.eeDeltaCmd(clickedMesh.cbArgs);
        }
    };

    self.canvasMousedownCB = function (event) {
        var clickedMesh = self.getMeshPointedAt(event);
        if (clickedMesh !== null) {
            clickedMesh.mesh.material.color.set(clickedMesh.mesh.userData.clickColor);
            self.clickedMesh = clickedMesh;
        }
    };

    self.canvasMouseupCB = function (event) {
        var clickedMesh = self.getMeshPointedAt(event);
        if (clickedMesh !== null) {
            clickedMesh.mesh.material.color.set(clickedMesh.mesh.userData.hoverColor);
        } else {
            if (self.clickedMesh !== null) {
                self.clickedMesh.mesh.material.color.set(self.clickedMesh.mesh.userData.defaultColor);
                self.clickedMesh = null;
            }
        }
    };

    self.canvasMouseMoveCB = function (event) {
        var overMesh = self.getMeshPointedAt(event);
        if (overMesh === undefined) {return;}
        if (overMesh === null) {
            if (self.hoveredMesh !== null){
                self.hoveredMesh.mesh.material.color.set(self.hoveredMesh.mesh.userData.defaultColor);
                self.hoveredMesh = null;
            }
        } else {
            if (self.hoveredMesh === null) {
                overMesh.mesh.material.color.set(overMesh.mesh.userData.hoverColor);
                self.hoveredMesh = overMesh;
            } else if (overMesh !== self.hoveredMesh) {
                overMesh.mesh.material.color.set(overMesh.mesh.userData.hoverColor);
                self.hoveredMesh.mesh.material.color.set(self.hoveredMesh.mesh.userData.defaultColor);
                self.hoveredMesh = overMesh;
            }
        }
    };

    self.rotArrowLoader = new THREE.ColladaLoader();
    var arrowOnLoad = function (collada) {
        var arrowGeom = collada.scene.children[0].children[0].geometry.clone();
        var baseMaterial = new THREE.MeshLambertMaterial();
        baseMaterial.transparent = true;
        baseMaterial.opacity = 0.50;
        self.rotArrows = {};
        var scaleX = 0.00075;
        var scaleY = 0.00075;
        var scaleZ = 0.00075;
        var edgeColor = new THREE.Color(0.1,0.1,0.1);
        var edgeMinAngle = 45;
        var edgeOpacity = 0.6;

        //Create arrow meshes for each directional control
        var mesh, edges, pos, rot, mat, cbArgs;
        // X-Positive Rotation 3D Arrow
        baseMaterial.color.setRGB(2.75,0.1,0.1); //Something funny means RGB colors are rendered on a 0-3 scale...
        mesh = new THREE.Mesh(arrowGeom.clone(), baseMaterial.clone());
        mesh.userData.direction = 'xn';
        mesh.userData.defaultColor = new THREE.Color().setRGB(2.75, 0.1, 0.1);
        mesh.userData.hoverColor = new THREE.Color().setRGB(3, 0.1, 0.1);
        mesh.userData.clickColor = new THREE.Color().setRGB(3, 1, 1);
        mesh.userData.side = self.side;
        mesh.scale.set(scaleX, scaleY, scaleZ);
        edges = new THREE.EdgesHelper(mesh, edgeColor, edgeMinAngle);
        edges.material.transparent = true;
        edges.material.opacity = edgeOpacity;
        pos = new THREE.Vector3(-0.1, 0.13, 0.13);
        rot = new THREE.Euler(Math.PI/2, 0, -Math.PI/2);
        mat = new THREE.Matrix4().makeRotationFromEuler(rot);
        mat.setPosition(pos);
        cbArgs = {'roll':1};
        self.rotArrows[mesh.userData.direction] = {'mesh': mesh, 'edges': edges, 'transform': mat, 'cbArgs': cbArgs};
        // X-Negative Rotation 3D Arrow
        mesh = new THREE.Mesh(arrowGeom.clone(), baseMaterial.clone());
        mesh.userData.direction = 'xp';
        mesh.userData.defaultColor = new THREE.Color().setRGB(2.75,0.1,0.1);
        mesh.userData.hoverColor = new THREE.Color().setRGB(3, 0.1, 0.1);
        mesh.userData.clickColor = new THREE.Color().setRGB(3, 1, 1);
        mesh.userData.side = self.side;
        mesh.scale.set(scaleX, scaleY, scaleZ);
        edges = new THREE.EdgesHelper(mesh, edgeColor, edgeMinAngle);
        edges.material.transparent = true;
        edges.material.opacity = edgeOpacity;
        pos = new THREE.Vector3(-0.1, -0.13, 0.13);
        rot = new THREE.Euler(-Math.PI/2, 0, Math.PI/2);
        mat = new THREE.Matrix4().makeRotationFromEuler(rot);
        mat.setPosition(pos);
        cbArgs = {'roll':-1};
        self.rotArrows[mesh.userData.direction] = {'mesh': mesh, 'edges': edges, 'transform': mat, 'cbArgs': cbArgs};
        // Y-Positive Rotation 3D Arrow
        baseMaterial.color.setRGB(0.1, 2.75, 0.1);
        mesh = new THREE.Mesh(arrowGeom.clone(), baseMaterial.clone());
        mesh.userData.direction = 'yn';
        mesh.userData.defaultColor = new THREE.Color().setRGB(0.1, 2.75, 0.1);
        mesh.userData.hoverColor = new THREE.Color().setRGB(0.1, 3, 0.1);
        mesh.userData.clickColor = new THREE.Color().setRGB(1, 3, 1);
        mesh.userData.side = self.side;
        mesh.scale.set(scaleX, scaleY, scaleZ);
        edges = new THREE.EdgesHelper(mesh, edgeColor, edgeMinAngle);
        edges.material.transparent = true;
        edges.material.opacity = edgeOpacity;
        pos = new THREE.Vector3(-0.13, -0.025, -0.13);
        rot = new THREE.Euler(0, 0, 0);
        mat = new THREE.Matrix4().makeRotationFromEuler(rot);
        mat.setPosition(pos);
        cbArgs = {'pitch':1};
        self.rotArrows[mesh.userData.direction] = {'mesh': mesh, 'edges': edges, 'transform': mat, 'cbArgs': cbArgs};
        // Y-Negative Rotation 3D Arrow
        mesh = new THREE.Mesh(arrowGeom.clone(), baseMaterial.clone());
        mesh.userData.direction = 'yp';
        mesh.userData.defaultColor = new THREE.Color().setRGB(0.1, 2.75, 0.1);
        mesh.userData.hoverColor = new THREE.Color().setRGB(0.1, 3, 0.1);
        mesh.userData.clickColor = new THREE.Color().setRGB(1, 3, 1);
        mesh.userData.side = self.side;
        mesh.scale.set(scaleX, scaleY, scaleZ);
        edges = new THREE.EdgesHelper(mesh, edgeColor, edgeMinAngle);
        edges.material.transparent = true;
        edges.material.opacity = edgeOpacity;
        pos = new THREE.Vector3(-0.13, 0.025, 0.13);
        rot = new THREE.Euler(Math.PI,0,0);
        mat = new THREE.Matrix4().makeRotationFromEuler(rot);
        mat.setPosition(pos);
        cbArgs = {'pitch':-1};
        self.rotArrows[mesh.userData.direction] = {'mesh': mesh, 'edges': edges, 'transform': mat, 'cbArgs': cbArgs};
        // Z-Positive Rotation 3D Arrow
        baseMaterial.color.setRGB(0.1,0.1,2.75);
        mesh = new THREE.Mesh(arrowGeom.clone(), baseMaterial.clone());
        mesh.userData.direction = 'zp';
        mesh.userData.defaultColor = new THREE.Color().setRGB(0.1, 0.1, 2.75);
        mesh.userData.hoverColor = new THREE.Color().setRGB(0.1, 0.1, 3);
        mesh.userData.clickColor = new THREE.Color().setRGB(1, 1, 3);
        mesh.userData.side = self.side;
        mesh.scale.set(scaleX, scaleY, scaleZ);
        edges = new THREE.EdgesHelper(mesh, edgeColor, edgeMinAngle);
        edges.material.transparent = true;
        edges.material.opacity = edgeOpacity;
        pos = new THREE.Vector3(-0.13, -0.13, 0.025);
        rot = new THREE.Euler(-Math.PI/2, 0, 0);
        mat = new THREE.Matrix4().makeRotationFromEuler(rot);
        mat.setPosition(pos);
        cbArgs = {'yaw':1};
        self.rotArrows[mesh.userData.direction] = {'mesh': mesh, 'edges': edges, 'transform': mat, 'cbArgs': cbArgs};
        // Z-Negative Rotation 3D Arrow
        mesh = new THREE.Mesh(arrowGeom.clone(), baseMaterial.clone());
        mesh.userData.direction = 'zn';
        mesh.userData.defaultColor = new THREE.Color().setRGB(0.1, 0.1, 2.75);
        mesh.userData.hoverColor = new THREE.Color().setRGB(0.1, 0.1, 3);
        mesh.userData.clickColor = new THREE.Color().setRGB(1, 1, 3);
        mesh.userData.side = self.side;
        mesh.scale.set(scaleX, scaleY, scaleZ);
        edges = new THREE.EdgesHelper(mesh, edgeColor, edgeMinAngle);
        edges.material.transparent = true;
        edges.material.opacity = edgeOpacity;
        pos = new THREE.Vector3(-0.13, 0.13, -0.025);
        rot = new THREE.Euler(Math.PI/2, 0, 0);
        mat = new THREE.Matrix4().makeRotationFromEuler(rot);
        mat.setPosition(pos);
        cbArgs = {'yaw':-1};
        self.rotArrows[mesh.userData.direction] = {'mesh': mesh, 'edges': edges, 'transform': mat, 'cbArgs': cbArgs};

        for (var dir in self.rotArrows) {
            self.rotArrows[dir].mesh.visible = false;
            self.rotArrows[dir].edges.visible = false;
            RFH.viewer.scene.add(self.rotArrows[dir].mesh);
            RFH.viewer.scene.add(self.rotArrows[dir].edges);
        }
    };

    var arrowOnProgress = function (data) {
        console.log("Loading Rotation Arrow Collada Mesh: ", data.loaded/data.total);
    };

    self.rotArrowLoader.load('./data/Curved_Arrow_Square.dae', arrowOnLoad, arrowOnProgress);


    self.updateRotImage = function () {
        if (self.eeTF === null) { return; }
        var q = new THREE.Quaternion(self.eeTF.rotation.x,
                                     self.eeTF.rotation.y,
                                     self.eeTF.rotation.z,
                                     self.eeTF.rotation.w);
        var tfMat = new THREE.Matrix4().makeRotationFromQuaternion(q);
        tfMat.setPosition(new THREE.Vector3(self.eeTF.translation.x,
                                            self.eeTF.translation.y,
                                            self.eeTF.translation.z));

        var arrowInWorldFrame = new THREE.Matrix4();
        var arrowPos = new THREE.Vector3();
        var arrowQuat = new THREE.Quaternion();
        var arrowScale = new THREE.Vector3();
        for (var dir in self.rotArrows) {
            arrowInWorldFrame.multiplyMatrices(tfMat, self.rotArrows[dir].transform);
            arrowInWorldFrame.decompose(arrowPos, arrowQuat, arrowScale);
            self.rotArrows[dir].mesh.position.set(arrowPos.x, arrowPos.y, arrowPos.z);
            self.rotArrows[dir].mesh.quaternion.set(arrowQuat.x, arrowQuat.y, arrowQuat.z, arrowQuat.w);
        }
        RFH.viewer.renderer.render(RFH.viewer.scene, RFH.viewer.camera);
    };

};
