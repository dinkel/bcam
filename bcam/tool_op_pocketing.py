from __future__ import absolute_import, division, print_function

import math
from bcam.tool_operation import ToolOperation, TOEnum, TOResult
from bcam.tool_abstract_follow import TOAbstractFollow
from bcam.generalized_setting import TOSetting, TOSTypes
from bcam.calc_utils import (find_vect_normal, mk_vect, normalize, vect_sum,
                             vect_len, linearized_path_aabb,
                             find_center_of_mass, sign, LineUtils)
from bcam.elements import ELine, EArc, EPoint
from bcam.singleton import Singleton

from logging import debug, info, warning, error, critical
from bcam.util import dbgfname

import json
import cairo
from multiprocessing import Process, Pipe


class TOPocketing(TOAbstractFollow):
    def __init__(self, state, depth=0, index=0, offset=0, data=None):
        super(TOAbstractFollow, self).__init__(state)
        self.state = state
        self.name = TOEnum.pocket
        self.draw_list = []
        self.process = None

        if data == None:
            self.index = index
            self.depth = depth
            self.offset = (offset if offset!=0 else self.state.settings.get_tool().diameter/2.0)
            self.old_offset = offset
            self.path = None
        else:
            self.deserialize(data)
        self.display_name = TOEnum.pocket+" "+str(self.index)

    def serialize(self):
        return {'type': 'topocketing', 'path_ref': self.path.name, 'depth': self.depth, 'index': self.index, 'offset': self.offset}

    def __draw_elements(self, ctx):
        if self.draw_list != None:
            for e in self.draw_list:
                e.draw_element(ctx)
                ctx.stroke()

    def draw(self, ctx):
        if self.display:
            ctx.set_line_join(cairo.LINE_JOIN_ROUND)
            ctx.set_line_cap(cairo.LINE_CAP_ROUND)
            self.set_lt(ctx)
            self.__draw_elements(ctx)

            self.set_fill_lt(ctx)
            self.__draw_elements(ctx)

    def __linearize_path(self, path, tolerance):
        linearized_path = []
        for e in path:
            if type(e).__name__ == "EArc":
                lpath = e.to_line_sequence(tolerance)
                linearized_path += lpath
            elif type(e).__name__ == "ECircle":
                lpath = e.to_line_sequence(tolerance)
                linearized_path += lpath
            elif type(e).__name__ == "ELine":
                linearized_path.append(e)
        return linearized_path

    # returns tuple [0]: if halfcrosses, [1]: if up
    def __is_element_halfcrossing(self, el_coords):
        if abs(el_coords[0][1])<0.0001 and abs(el_coords[1][1])>0.0001:
            if el_coords[1][1] > 0:
                return True, True
            else:
                return True, False
        if abs(el_coords[1][1])<0.0001 and abs(el_coords[0][1])>0.0001:
            if el_coords[0][1] > 0:
                return True, False
            else:
                return True, True
        return False, False

    def __is_element_crossing(self, el_coords):
        return sign(el_coords[0][1]) != sign(el_coords[1][1])

    def __is_crossing_up(self, el_coords):
        if el_coords[1][1] > el_coords[0][1]:
            return True
        return False

    def __is_point_at_left(self, pt, element, up):        
        v1x = element.start[0]-pt[0]
        v1y = element.start[1]-pt[1]

        v2x = element.end[0]-element.start[0]
        v2y = element.end[1]-element.start[1]

        cross_product = v1x*v2y-v1y*v2x
        if (up and (cross_product > 0)):
            return True
        elif (not up) and (cross_product < 0):
            return True
        return False

    def __is_pt_inside_path_winding(self, pt, path):
        # if pt[0]<-26 and pt[1]<-16:
        #     dbgfname()
        e = path[0]

        turns = 0
        
        for e in path:
            sx = e.start[0] - pt[0]
            sy = e.start[1] - pt[1]
            ex = e.end[0] - pt[0]
            ey = e.end[1] - pt[1]
            el_coords = [[sx, sy], [ex, ey]]
            halfcross, up = self.__is_element_halfcrossing(el_coords)
            # if pt[0]<-26 and pt[1]<-16:
            #     debug("  e: "+str(el_coords))
            #     debug("  halfcross: "+str(halfcross)+" up: "+str(up))
            if halfcross:
                if self.__is_point_at_left(pt, e, up):
                    if up:
                        turns+=0.5
                    else:
                        turns-=0.5
            elif self.__is_element_crossing(el_coords):
                up = self.__is_crossing_up(el_coords)
                # if pt[0]<-26 and pt[1]<-16:
                #     debug("  e: "+str(el_coords))
                #     debug("  cross: True, up: "+str(up))
                
                if self.__is_point_at_left(pt, e, up):
                    if up:
                        turns+=1
                    else:
                        turns-=1

        # if pt[0]<-26 and pt[1]<-16:
        #     debug("  turns: %f"%(turns,))
            
        if (abs(turns) >= 1):
            return True
        return False

    def build_points(self, path):
        dbgfname()
        debug("  linearizing path")
        lpath = self.__linearize_path(path, 0.1)
        #lpath = path

        path_aabb = linearized_path_aabb(lpath)
        left = path_aabb.left - 10
        right = path_aabb.right + 10
        top = path_aabb.top + 10
        bottom = path_aabb.bottom - 10
        points = []
        step = 0.5
        total_points = int(right-left+1)*int(top-bottom+1)//step
        debug("  AABB: "+str(path_aabb))
        point_counter = 0
        x = left
        while (x<right):
            y = bottom
            while (y<top):
                debug("  checking pt: "+str(x)+" "+str(y)+" "+str(point_counter)+"/"+str(total_points))
                if self.__is_pt_inside_path_winding((x, y), lpath):
                    points.append(EPoint(center=[x, y], lt=self.state.settings.get_def_lt()))
                    debug("  it fits")
                point_counter += 1
                y += step
            x += step
        debug("  points: "+str(points))
        return points

    def __check_if_pt_is_close(self, pt, path):
        offset = self.offset
        for e in path:
            cu = e.get_cu()
            if (cu.distance_to_pt(pt)<=offset):
                return True
        return False

    def build_circles(self, path):
        dbgfname()
        debug("  linearizing path")
        lpath = self.__linearize_path(path, 0.1)
        #x, y = find_center_of_mass(lpath)

        path_aabb = linearized_path_aabb(lpath)
        left = path_aabb.left
        right = path_aabb.right
        top = path_aabb.top
        bottom = path_aabb.bottom
        x = (right-left)/2.0+left
        y = (top-bottom)/2.0+bottom
        
        debug("  building paths")
        tool_paths = []
        r = 0
        max_r = math.sqrt(((right-left)/2.0)**2+((top-bottom)/2.0)**2)
        tool_radius = self.tool.diameter/2.0
        while r < max_r:
            debug("  r: %f"%(r,))
            r+=tool_radius
            angle = 0
            cur_x = x+r*math.cos(angle)
            cur_y = y+r*math.sin(angle)
            is_inside = False
            start_angle = 0
            end_angle = 0
            if (self.__is_pt_inside_path_winding([cur_x, cur_y], lpath)):
                debug("  cx: %f, cy: %f"%(cur_x, cur_y))
                debug("  s start: "+str(start_angle))
                is_inside = True
            if self.__check_if_pt_is_close([cur_x, cur_y], lpath):
                if is_inside:
                    is_inside = False

            while angle<=360:
                cur_x = x+r*math.cos(math.radians(angle))
                cur_y = y+r*math.sin(math.radians(angle))
                close = self.__check_if_pt_is_close([cur_x, cur_y], lpath)
                if not close:
                    in_winding = self.__is_pt_inside_path_winding([cur_x, cur_y], lpath)
                    if in_winding and (not is_inside):
                        debug("  cx: %f, cy: %f"%(cur_x, cur_y))
                        debug("  start: "+str(start_angle))
                        start_angle = angle
                        is_inside = True
                    elif (not in_winding) and (is_inside):
                        debug("  cx: %f, cy: %f"%(cur_x, cur_y))
                        debug("  end: "+str(end_angle))
                        end_angle = angle
                        is_inside = False
                        tool_paths.append(EArc(center=[x, y], radius=r, startangle=start_angle, endangle=end_angle, lt=self.state.settings.get_def_lt()))
                elif is_inside:
                    debug("  cx: %f, cy: %f"%(cur_x, cur_y))
                    debug("  close end: "+str(end_angle))
                    is_inside = False
                    end_angle = angle
                    tool_paths.append(EArc(center=[x, y], radius=r, startangle=start_angle, endangle=end_angle, lt=self.state.settings.get_def_lt()))

                    
                angle += 0.1
            if is_inside:
                debug("  cx: %f, cy: %f"%(cur_x, cur_y))
                debug("  e end: "+str(angle))
                tool_paths.append(EArc(center=[x, y], radius=r, startangle=start_angle, endangle=angle-0.1, lt=self.state.settings.get_def_lt()))

                        
        return tool_paths
            
    def deserialize(self, data):
        self.depth = data["depth"]
        self.index = data["index"]
        self.offset = data["offset"]
        self.old_offset = 0
        p = self.try_load_path_by_name(data["path_ref"], self.state)
        self.path = p

    def get_settings_list(self):            
        settings_lst = [TOSetting(TOSTypes.float, 0, self.state.settings.material.thickness, self.depth, "Depth, mm: ", self.set_depth_s),
                        TOSetting(TOSTypes.float, 0, None, self.offset, "Offset, mm: ", self.set_offset_s),
                        TOSetting(TOSTypes.button, display_name="Recalculate", parent_cb=self.clicked_recalculate)
        ]
        return settings_lst

    def set_depth_s(self, setting):
        self.depth = setting.new_value

    def set_offset_s(self, setting):
        self.offset = setting.new_value

    def clicked_recalculate(self, setting):
        dbgfname()
        op = Singleton.state.get_operation_in_progress()
        debug("  current operation:" + str(op))
        if op==None:
            if self.offset != self.old_offset:
                self.old_offset = self.offset
                Singleton.state.set_operation_in_progress(self)
                if self.apply(self.path)!=TOResult.ok:
                    debug("  pushing event to update pocketing state")
                    Singleton.ep.push_event(Singleton.ee.pocket_tool_click, None)

    def build_circles_wrapper(self, pipe, path):
        draw_list = self.build_circles(path.ordered_elements)
        pipe.send(draw_list)
        pipe.close()

    def apply(self, path):
        #dbgfname()
        if path != None:
            if path.operations[self.name]:
                if path.ordered_elements!=None:
                    self.path = path
                    parent, child = Pipe()
                    self.parent = parent
                    debug("  starting subprocess")
                    self.process = Process(target=self.build_circles_wrapper, args=(child, path))
                    self.process.start()
                    if self.process.is_alive():
                        return TOResult.repeat
                    self.draw_list = self.parent.recv()
                    debug("  joining: "+str(self.draw_list))
                    self.process.join()
                    self.process = None
                    return TOResult.ok
        else:
            if self.process != None:
                if self.process.is_alive():
                    return TOResult.repeat
                self.draw_list = self.parent.recv()
                debug("  joining: "+str(self.draw_list))
                self.process.join()
                self.process = None
                return TOResult.ok
        return TOResult.failed

    def get_gcode(self):
        cp = self.tool.current_position
        out = ""
        new_pos = [cp[0], cp[1], self.tool.default_height]
        out+= self.state.settings.default_pp.move_to_rapid(new_pos)
        self.tool.current_position = new_pos


        for step in range(int(self.depth/(self.tool.diameter/2.0))+1):
            for e in self.draw_list:
                start = list(e.start)
                new_pos = start[:2]+[self.tool.default_height]
                out+=self.state.settings.default_pp.move_to_rapid(new_pos)
                self.tool.current_position = new_pos

                out += self.process_el_to_gcode(e, step)

                new_pos = self.tool.current_position[:2]+[self.tool.default_height]
                out+=self.state.settings.default_pp.move_to_rapid(new_pos)
                self.tool.current_position = new_pos
        return out

    def __repr__(self):
        return "<Pocketing>"
