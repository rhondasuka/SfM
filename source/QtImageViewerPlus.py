# TagLab                                               
# A semi-automatic segmentation tool                                    
#
# Copyright(C) 2019                                         
# Visual Computing Lab                                           
# ISTI - Italian National Research Council                              
# All rights reserved.                                                      
                                                                          
# This program is free software; you can redistribute it and/or modify      
# it under the terms of the GNU General Public License as published by      
# the Free Software Foundation; either version 2 of the License, or         
# (at your option) any later version.                                       
                                                                           
# This program is distributed in the hope that it will be useful,           
# but WITHOUT ANY WARRANTY; without even the implied warranty of            
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the             
#GNU General Public License (http://www.gnu.org/licenses/gpl.txt)          
# for more details.                                               

""" PyQt image viewer widget for a QPixmap in a QGraphicsView scene with mouse zooming and panning.
    The viewer has also drawing capabilities.
"""

import os.path
from PyQt5.QtCore import Qt, QPointF, QRectF, QFileInfo, QDir, pyqtSlot, pyqtSignal, QT_VERSION_STR
from PyQt5.QtGui import QImage, QPixmap, QPainter, QPainterPath, QPen, QImageReader, QFont
from PyQt5.QtWidgets import QApplication, QGraphicsView, QGraphicsScene, QFileDialog, QGraphicsItem, QGraphicsSimpleTextItem

from source.Undo import Undo
from source.Project import Project
from source.Image import Image
from source.Annotation import Annotation
from source.Annotation import Blob
from source.Tools import Tools
from source.Label import Label

from source.QtImageViewer import QtImageViewer

import random as rnd

#note on ZValue:
# 0: image
# 1: blobs
# 2: blob text
# 3: selected blobs
# 4: selected blobs text
# 5: pick points and tools
class TextItem(QGraphicsSimpleTextItem):
    def __init__(self, text, font):
        QGraphicsSimpleTextItem.__init__(self)
        self.setText(text)
        self.setFont(font)

    def paint(self, painter, option, widget):
        painter.translate(self.boundingRect().topLeft())
        super().paint(painter, option, widget)
        painter.translate(-self.boundingRect().topLeft())

    def boundingRect(self ):
        b = super().boundingRect()
        return QRectF(b.x()-b.width()/2.0, b.y()-b.height()/2.0, b.width(), b.height())


#TODO: crackwidget uses qimageviewerplus to draw an image.
#circular dependency. create a viewer and a derived class which also deals with the rest.
class QtImageViewerPlus(QtImageViewer):
    """
    PyQt image viewer widget with annotation capabilities.
    QGraphicsView handles a scene composed by an image plus shapes (rectangles, polygons, blobs).
    The input image (it must be a QImage) is internally converted into a QPixmap.
    """

    # Mouse button signals emit image scene (x, y) coordinates.
    leftMouseButtonPressed = pyqtSignal(float, float)
    rightMouseButtonPressed = pyqtSignal(float, float)
    leftMouseButtonReleased = pyqtSignal(float, float)
    rightMouseButtonReleased = pyqtSignal(float, float)
    #leftMouseButtonDoubleClicked = pyqtSignal(float, float)
    rightMouseButtonDoubleClicked = pyqtSignal(float, float)
    mouseMoveLeftPressed = pyqtSignal(float, float)
    mouseMoved = pyqtSignal(float, float)
    selectionChanged = pyqtSignal()
    selectionReset = pyqtSignal()
    annotationsChanged = pyqtSignal()

    # custom signal
    updateInfoPanel = pyqtSignal(Blob)

    activated = pyqtSignal()
    newSelection = pyqtSignal()

    def __init__(self, taglab_dir):
        QtImageViewer.__init__(self)

        self.logfile = None #MUST be inited in Taglab.py
        self.project = Project()
        self.image = None
        self.channel = None
        self.annotations = Annotation()
        self.selected_blobs = []
        self.taglab_dir = taglab_dir
        self.tools = Tools(self)
        self.tools.createTools()

        self.undo_data = Undo()

        self.dragSelectionStart = None
        self.dragSelectionRect = None
        self.dragSelectionStyle = QPen(Qt.white, 1, Qt.DashLine)
        self.dragSelectionStyle.setCosmetic(True)

        # Set scrollbar
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)


        # DRAWING SETTINGS
        self.border_pen = QPen(Qt.black, 3)
        #        pen.setJoinStyle(Qt.MiterJoin)
        #        pen.setCapStyle(Qt.RoundCap)
        self.border_pen.setCosmetic(True)
        self.border_selected_pen = QPen(Qt.white, 3)
        self.border_selected_pen.setCosmetic(True)

        self.showCrossair = False
        self.mouseCoords = QPointF(0, 0)
        self.crackWidget = None

        self.setContextMenuPolicy(Qt.CustomContextMenu)

        self.refine_grow = 0.0 #maybe should in in tools
        self.refine_original_mask = None
        self.refine_original_blob = None

        self.active_label = None

    def setProject(self, project):

        self.project = project

    def setImage(self, image, channel_idx=0):
        """
        Set the image to visualize. The first channel is visualized unless otherwise specified.
        """

        self.image = image
        self.annotations = image.annotations
        self.selected_blobs = []
        self.selectionChanged.emit()

        for blob in self.annotations.seg_blobs:
            self.drawBlob(blob)

        self.scene.invalidate()

        self.tools.tools['RULER'].setPxToMM(image.pixelSize())
        self.px_to_mm = image.pixelSize()
        self.setChannel(image.channels[channel_idx])

        self.activated.emit()

    def updateImageProperties(self):
        """
        The properties of the image have been changed. This function updates the viewer accordingly.
        NOTE: In practice, only the pixel size needs to be updated.
        """

        self.tools.tools['RULER'].setPxToMM(self.image.pixelSize())
        self.px_to_mm = self.image.pixelSize()


    def setChannel(self, channel, switch=False):
        """
        Set the image channel to visualize. If the channel has not been previously loaded it is loaded and cached.
        """

        if self.image is None:
            raise("Image has not been previously set in ViewerPlus")

        self.channel = channel

        if channel.qimage is not None:
            img = channel.qimage
        else:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            img = channel.loadData()
            QApplication.restoreOverrideCursor()

        if img.isNull():
            (filename, filter) = QFileDialog.getOpenFileName(self, "Couldn't find the map, please select it:",
                                                                       QFileInfo(channel.filename).dir().path(),
                                                                       "Image Files (*.png *.jpg)")
            dir = QDir(self.taglab_dir)
            channel.filename = dir.relativeFilePath(filename)
            img = channel.loadData()
            if img.isNull():
                raise Exception("Could not load or find the image: " + filename)

        if switch:
            self.setChannelImg(img, self.zoom_factor)
        else:
            self.setChannelImg(img)

    def setChannelImg(self, channel_img, zoomf=0.0):
        """
        Set the scene's current image (input image must be a QImage)
        For calculating the zoom factor automatically set it to 0.0.
        """
        self.setImg(channel_img, zoomf)

    def clear(self):

        QtImageViewer.clear(self)
        self.selected_blobs = []
        self.selectionChanged.emit()
        self.undo_data = Undo()

        for blob in self.annotations.seg_blobs:
            self.undrawBlob(blob)
            del blob

        self.annotations = Annotation()


    def drawBlob(self, blob, prev=False):
        # if it has just been created remove the current graphics item in order to set it again
        if blob.qpath_gitem is not None:
            self.scene.removeItem(blob.qpath_gitem)
            self.scene.removeItem(blob.id_item)
            del blob.qpath_gitem
            del blob.id_item
            blob.qpath_gitem = None
            blob.id_item = None

        blob.setupForDrawing()

        if prev is True:
            pen = self.border_pen_for_appended_blobs
        else:
            pen = self.border_selected_pen if blob in self.selected_blobs else self.border_pen
        brush = self.project.classBrushFromName(blob)

        blob.qpath_gitem = self.scene.addPath(blob.qpath, pen, brush)
        blob.qpath_gitem.setZValue(1)

        font_size = 12
        blob.id_item = TextItem(str(blob.id),  QFont("Calibri", font_size, QFont.Bold))
        self.scene.addItem(blob.id_item)
        blob.id_item.setPos(blob.centroid[0], blob.centroid[1])
        blob.id_item.setTransformOriginPoint(QPointF(blob.centroid[0] + 14.0, blob.centroid[1] + 14.0))
        blob.id_item.setZValue(2)
        blob.id_item.setBrush(Qt.white)
        blob.id_item.setOpacity(0.8)

        #blob.id_item.setDefaultTextColor(Qt.white)
        #blob.id_item.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        #blob.qpath_gitem.setOpacity(self.transparency_value)


    def undrawBlob(self, blob):
        self.scene.removeItem(blob.qpath_gitem)
        self.scene.removeItem(blob.id_item)
        blob.qpath = None
        blob.qpath_gitem = None
        blob.id_item = None
        self.scene.invalidate()


    def applyTransparency(self, value):
        self.transparency_value = value / 100.0
        # current annotations
        for blob in self.annotations.seg_blobs:
            blob.qpath_gitem.setOpacity(self.transparency_value)

    #used for crossair cursor
    def drawForeground(self, painter, rect):
        if self.showCrossair:
            painter.setClipRect(rect)
            pen = QPen(Qt.white, 1)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawLine(self.mouseCoords.x(), rect.top(), self.mouseCoords.x(), rect.bottom())
            painter.drawLine(rect.left(), self.mouseCoords.y(), rect.right(), self.mouseCoords.y())


#TOOLS and SELECTIONS

    def setTool(self, tool):

        if not self.isVisible():
            return

        QApplication.setOverrideCursor(Qt.ArrowCursor)

        self.tools.setTool(tool)

        if tool in ["FREEHAND", "RULER", "DEEPEXTREME"] or (tool in ["CUT", "EDITBORDER"] and len(self.selected_blobs) > 1):
            self.resetSelection()

        if tool == "WORKINGAREA":
            QApplication.setOverrideCursor(Qt.CrossCursor)

        if tool == "WATERSHED":

            self.tools.tools["WATERSHED"].scribbles.setScaleFactor(self.zoom_factor)

            label_info = self.project.labels.get(self.active_label)
            if label_info is not None:
                self.tools.tools["WATERSHED"].setActiveLabel(label_info)
            else:
                lbl = Label("", "", fill=[0, 0, 0])
                self.tools.tools["WATERSHED"].setActiveLabel(lbl)

        if tool == "DEEPEXTREME":
            self.showCrossair = True
        else:
            self.showCrossair = False

        if tool == "MOVE":
            self.enablePan()
        else:
            self.disablePan()

        if tool == "MATCH":
            self.enablePan()

    def resetTools(self):
        self.tools.resetTools()
        self.showCrossair = False
        self.scene.invalidate(self.scene.sceneRect())
        self.setDragMode(QGraphicsView.NoDrag)

#TODO not necessarily a slot
    @pyqtSlot(float, float)
    def selectOp(self, x, y):
        """
        Selection operation.
        """

        self.logfile.info("[SELECTION][DOUBLE-CLICK] Selection starts..")

        if self.tools.tool in ["RULER", "DEEPEXTREME"]:
            return

        if not (Qt.ShiftModifier & QApplication.queryKeyboardModifiers()):
            self.resetSelection()

        selected_blob = self.annotations.clickedBlob(x, y)

        if selected_blob:
            if selected_blob in self.selected_blobs:
                self.removeFromSelectedList(selected_blob)
            else:
                self.addToSelectedList(selected_blob)
                self.updateInfoPanel.emit(selected_blob)

        if len(self.selected_blobs) == 1:
            self.newSelection.emit()
        self.logfile.info("[SELECTION][DOUBLE-CLICK] Selection ends.")


#MOUSE EVENTS

    def mousePressEvent(self, event):
        """ Start mouse pan or zoom mode.
        """
        self.activated.emit()

        scenePos = self.mapToScene(event.pos())

        mods = event.modifiers()

        if event.button() == Qt.LeftButton:
            (x, y) = self.clipScenePos(scenePos)
            #used from area selection and pen drawing,

            if (self.panEnabled and not (mods & Qt.ShiftModifier)) or (mods & Qt.ControlModifier):
                self.setDragMode(QGraphicsView.ScrollHandDrag)
            elif self.tools.tool == "MATCH":
                self.tools.leftPressed(x, y, mods)

            elif mods & Qt.ShiftModifier:
                self.dragSelectionStart = [x, y]
                self.logfile.info("[SELECTION][DRAG] Selection starts..")

            else:
                self.tools.leftPressed(x, y)
                #self.leftMouseButtonPressed.emit(clippedCoords[0], clippedCoords[1])


        # PANNING IS ALWAYS POSSIBLE WITH WHEEL BUTTON PRESSED (!)
        # if event.button() == Qt.MiddleButton:
        #     self.setDragMode(QGraphicsView.ScrollHandDrag)

        if event.button() == Qt.RightButton:
            clippedCoords = self.clipScenePos(scenePos)
            self.rightMouseButtonPressed.emit(clippedCoords[0], clippedCoords[1])

        QGraphicsView.mousePressEvent(self, event)

    def mouseReleaseEvent(self, event):
        """ Stop mouse pan or zoom mode (apply zoom if valid).
        """
        QGraphicsView.mouseReleaseEvent(self, event)

        scenePos = self.mapToScene(event.pos())

        if event.button() == Qt.LeftButton:
            self.setDragMode(QGraphicsView.NoDrag)
            (x, y) = self.clipScenePos(scenePos)

            if self.dragSelectionStart:
                if abs(x - self.dragSelectionStart[0]) < 5 and abs(y - self.dragSelectionStart[1]) < 5:
                    self.selectOp(x, y)
                else:
                    self.dragSelectBlobs(x, y)
                    self.dragSelectionStart = None
                    if self.dragSelectionRect:
                        self.scene.removeItem(self.dragSelectionRect)
                        del self.dragSelectionRect
                        self.dragSelectionRect = None

                    self.logfile.info("[SELECTION][DRAG] Selection ends.")
            else:
                self.tools.leftReleased(x, y)

    def mouseMoveEvent(self, event):

        QGraphicsView.mouseMoveEvent(self, event)

        scenePos = self.mapToScene(event.pos())
        self.mouseMoved.emit(scenePos.x(), scenePos.y())

        if self.showCrossair == True:
            self.mouseCoords = scenePos
            self.scene.invalidate(self.sceneRect(), QGraphicsScene.ForegroundLayer)

        if event.buttons() == Qt.LeftButton:
            (x, y) = self.clipScenePos(scenePos)

            if self.dragSelectionStart:
                start = self.dragSelectionStart
                if not self.dragSelectionRect:
                    self.dragSelectionRect = self.scene.addRect(start[0], start[1], x - start[0],
                                                                           y - start[1], self.dragSelectionStyle)
                self.dragSelectionRect.setRect(start[0], start[1], x - start[0], y - start[1])
                return

            if Qt.ControlModifier & QApplication.queryKeyboardModifiers():
                return

            self.tools.mouseMove(x, y)


    def mouseDoubleClickEvent(self, event):

        scenePos = self.mapToScene(event.pos())

        if event.button() == Qt.LeftButton:
            self.selectOp(scenePos.x(), scenePos.y())


    def wheelEvent(self, event):
        """ Zoom in/zoom out.
        """

        mods = event.modifiers()

        if self.tools.tool == "WATERSHED" and mods & Qt.ShiftModifier:
            self.tools.tools["WATERSHED"].scribbles.setScaleFactor(self.zoom_factor)
            self.tools.wheel(event.angleDelta())
            return

        if self.zoomEnabled:

            view_pos = event.pos()
            scene_pos = self.mapToScene(view_pos)
            self.centerOn(scene_pos)


            pt = event.angleDelta()

            #uniform zoom.
            self.zoom_factor = self.zoom_factor*pow(pow(2, 1/2), pt.y()/100);
            if self.zoom_factor < self.ZOOM_FACTOR_MIN:
                self.zoom_factor = self.ZOOM_FACTOR_MIN
            if self.zoom_factor > self.ZOOM_FACTOR_MAX:
                self.zoom_factor = self.ZOOM_FACTOR_MAX

            self.resetTransform()
            self.scale(self.zoom_factor, self.zoom_factor)

            delta = self.mapToScene(view_pos) - self.mapToScene(self.viewport().rect().center())
            self.centerOn(scene_pos - delta)

            self.invalidateScene()
            #self.updateViewer()

        # PAY ATTENTION !! THE WHEEL INTERACT ALSO WITH THE SCROLL BAR !!
        #QGraphicsView.wheelEvent(self, event)

#VISIBILITY AND SELECTION

    def dragSelectBlobs(self, x, y):
        sx = self.dragSelectionStart[0]
        sy = self.dragSelectionStart[1]
        self.resetSelection()
        for blob in self.annotations.seg_blobs:
            visible = self.project.isLabelVisible(blob.class_name)
            if not visible:
                continue
            box = blob.bbox

            if sx > box[1] or sy > box[0] or x < box[1] + box[2] or y < box[0] + box[3]:
                continue
            self.addToSelectedList(blob)

    @pyqtSlot(str)
    def setActiveLabel(self, label):

        if self.tools.tool == "ASSIGN":
            self.tools.tools["ASSIGN"].setActiveLabel(label)

        if self.tools.tool == "WATERSHED":
            label_info = self.project.labels.get(label)
            if label_info is not None:
                self.tools.tools["WATERSHED"].setActiveLabel(label_info)

        self.active_label = label

    def setBlobVisible(self, blob, visibility):
        if blob.qpath_gitem is not None:
            blob.qpath_gitem.setVisible(visibility)
        if blob.id_item is not None:
            blob.id_item.setVisible(visibility)

    def updateVisibility(self):

        for blob in self.annotations.seg_blobs:
            visibility = self.project.isLabelVisible(blob.class_name)
            self.setBlobVisible(blob, visibility)



#SELECTED BLOBS MANAGEMENT

    def addToSelectedList(self, blob):
        """
        Add the given blob to the list of selected blob.
        """

        if blob in self.selected_blobs:
            self.logfile.info("[SELECTION] An already selected blob has been added to the current selection.")
        else:
            self.selected_blobs.append(blob)
            str = "[SELECTION] A new blob (" + blob.blob_name + ";" + blob.class_name + ") has been selected."
            self.logfile.info(str)

        if not blob.qpath_gitem is None:
            blob.qpath_gitem.setPen(self.border_selected_pen)
            blob.qpath_gitem.setZValue(3)
            blob.id_item.setZValue(4)
        else:
            print("blob qpath_qitem is None!")
        self.scene.invalidate()
        self.selectionChanged.emit()


    def removeFromSelectedList(self, blob):
        try:
            # safer if iterating over selected_blobs and calling this function.
            self.selected_blobs = [x for x in self.selected_blobs if not x == blob]
            if not blob.qpath_gitem is None:
                blob.qpath_gitem.setPen(self.border_pen)
                blob.qpath_gitem.setZValue(1)
                blob.id_item.setZValue(2)

            self.scene.invalidate()
        except Exception as e:
            print("Exception: e", e)
            pass
        self.selectionChanged.emit()

    def resetSelection(self):
        for blob in self.selected_blobs:
            if blob.qpath_gitem is None:
                print("Selected item with no path!")
            else:
                blob.qpath_gitem.setPen(self.border_pen)
                blob.qpath_gitem.setZValue(1)
                blob.id_item.setZValue(2)

        self.selected_blobs.clear()
        self.scene.invalidate(self.scene.sceneRect())
        self.selectionChanged.emit()
        self.selectionReset.emit()



#CREATION and DESTRUCTION of BLOBS
    def addBlob(self, blob, selected = False):
        """
        The only function to add annotations. will take care of undo and QGraphicItems.
        """
        self.undo_data.addBlob(blob)
        self.project.addBlob(self.image, blob)
        self.drawBlob(blob)
        if selected:
            self.addToSelectedList(blob)

        self.annotationsChanged.emit()

    def removeBlob(self, blob):
        """
        The only function to remove annotations.
        """
        self.removeFromSelectedList(blob)
        self.undrawBlob(blob)
        self.undo_data.removeBlob(blob)
        #self.annotations.removeBlob(blob)
        self.project.removeBlob(self.image, blob)

        self.annotationsChanged.emit()

    def updateBlob(self, old_blob, new_blob, selected = False):

        #self.annotations.updateBlob(old_blob, new_blob)
        self.project.updateBlob(self.image, old_blob, new_blob)

        self.removeFromSelectedList(old_blob)
        self.undrawBlob(old_blob)
        self.undo_data.removeBlob(old_blob)

        self.undo_data.addBlob(new_blob)
        self.drawBlob(new_blob)
        if selected:
            self.addToSelectedList(new_blob)

        self.annotationsChanged.emit()


    def deleteSelectedBlobs(self):

        for blob in self.selected_blobs:
            self.removeBlob(blob)
        self.saveUndo()

    def assignClass(self, class_name):
        """
        Assign the given class to the selected blobs.
        """
        for blob in self.selected_blobs:
            self.project.setBlobClass(self.image, blob, class_name)
            self.undo_data.setBlobClass(blob, class_name)
            brush = self.project.classBrushFromName(blob)
            blob.qpath_gitem.setBrush(brush)

        self.scene.invalidate()
        self.annotationsChanged.emit()

    def setBlobClass(self, blob, class_name):

        if blob.class_name == class_name:
            return

        self.project.setBlobClass(self.image, blob, class_name)
        self.undo_data.setBlobClass(blob, class_name)

        brush = self.project.classBrushFromName(blob)
        blob.qpath_gitem.setBrush(brush)

        self.scene.invalidate()
        self.annotationsChanged.emit()

#UNDO STUFF
#UNDO STUFF

    def saveUndo(self):
        self.undo_data.saveUndo()

    def undo(self):
        operation = self.undo_data.undo()
        if operation is None:
            return

        for blob in operation['remove']:
            message = "[UNDO][REMOVE] BLOBID={:d} VERSION={:d}".format(blob.id, blob.version)
            self.logfile.info(message)
            self.removeFromSelectedList(blob)
            self.undrawBlob(blob)
            self.annotations.removeBlob(blob)

        for blob in operation['add']:
            message = "[UNDO][ADD] BLOBID={:d} VERSION={:d}".format(blob.id, blob.version)
            self.logfile.info(message)
            self.annotations.addBlob(blob)
            self.selected_blobs.append(blob)
            self.selectionChanged.emit()
            self.drawBlob(blob)

        for (blob, class_name) in operation['class']:
            blob.class_name = class_name
            brush = self.project.classBrushFromName(blob)
            blob.qpath_gitem.setBrush(brush)

        self.updateVisibility()

    def redo(self):
        operation = self.undo_data.redo()
        if operation is None:
            return

        for blob in operation['add']:
            message = "[REDO][ADD] BLOBID={:d} VERSION={:d}".format(blob.id, blob.version)
            self.logfile.info(message)
            self.removeFromSelectedList(blob)
            self.undrawBlob(blob)
            self.annotations.removeBlob(blob)

        for blob in operation['remove']:
            message = "[REDO][REMOVE] BLOBID={:d} VERSION={:d}".format(blob.id, blob.version)
            self.logfile.info(message)
            self.annotations.addBlob(blob)
            self.selected_blobs.append(blob)
            self.selectionChanged.emit()
            self.drawBlob(blob)

        for (blob, class_name) in operation['newclass']:
            blob.class_name = class_name
            brush = self.project.classBrushFromName(blob)
            blob.qpath_gitem.setBrush(brush)

        self.updateVisibility()

