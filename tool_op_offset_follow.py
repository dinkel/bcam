import math
from tool_operation import ToolOperation, TOEnum
from tool_abstract_follow import TOAbstractFollow
from generalized_setting import TOSetting
from settings import settings
from calc_utils import find_vect_normal, mk_vect, normalize, vect_sum, vect_len
from elements import ELine, EArc

import cairo
import json

class TOOffsetFollow(TOAbstractFollow):
    def __init__(self, settings, depth=0, index=0, offset=0):
        super(TOAbstractFollow, self).__init__(settings)
        self.display_name = TOEnum.offset_follow+" "+str(index)
        self.name = TOEnum.offset_follow
        self.depth = depth
        self.offset = 0
        self.path = None
        self.offset_path = None

    def serialize(self):
        return {'type': 'tooffsetfollow', 'path_ref': self.path.name, 'depth': self.depth, 'index': self.index, 'offset': self.offset}

    def deserialize(self, data):
        pass

    def get_settings_list(self):
        settings_lst = [TOSetting("float", 0, settings.material.thickness, self.depth, "Depth, mm: ", self.set_depth_s),
                        TOSetting("float", None, None, 0, "Offset, mm: ", self.set_offset_s)]
        return settings_lst

    def set_depth_s(self, setting):
        self.depth = setting.new_value

    def set_offset_s(self, setting):
        self.offset = setting.new_value
        self.__build_offset_path(self.path)
        self.draw_list = self.offset_path
        
    def __build_offset_path(self, p):
        if len(p.elements)==0:
            return False
        if len(p.elements)==1:
            #check for circle here
            return
        
        new_elements = []
        s = p.elements[0].start
        e = p.elements[0].end
        nsn = p.elements[0].get_normalized_start_normal()
        s_pt = [nsn[0]*self.offset+s[0], nsn[1]*self.offset+s[1], 0]
        for i, e in enumerate(p.elements):
            sc = e.start # current start
            ec = e.end # current end
            

            if s_pt == None:
                nsn = e.get_normalized_start_normal()
                n = normalize(vect_sum(nsn, nen)) # sum of new start normal and prev end normal
                shift = sc
                s_pt = [n[0]*self.offset+shift[0], n[1]*self.offset+shift[1], 0]

            if i<len(p.elements)-1:
                nnsn = p.elements[i+1].get_normalized_start_normal()
                nen = e.get_normalized_end_normal()
                n = normalize(vect_sum(nnsn, nen)) # sum of next start normal and current end normal
                shift = ec
                e_pt = [n[0]*self.offset+shift[0], n[1]*self.offset+shift[1], 0]
            else:
                nen = e.get_normalized_end_normal()
                n = nen
                shift = ec
                e_pt = [n[0]*self.offset+shift[0], n[1]*self.offset+shift[1], 0]
            if type(e).__name__ == "ELine":
                ne = ELine(s_pt, e_pt, e.lt)
            elif type(e).__name__ == "EArc":
                ne = EArc(center=e.center, lt=e.lt, start=s_pt, end=e_pt)

            new_elements.append(ne)
            s_pt = None
            e_pt = None
        self.offset_path = new_elements
        
    def apply(self, path):
        if path.operations[self.name]:
            if path.ordered_elements!=None:
                self.path = path
                self.__build_offset_path(path)
                self.draw_list = self.offset_path
                return True
        return False

    def get_gcode(self):
        cp = self.tool.current_position
        out = ""
        new_pos = [cp[0], cp[1], self.tool.default_height]
        out+= settings.default_pp.move_to_rapid(new_pos)
        self.tool.current_position = new_pos

        start = self.offset_path[0].start

        new_pos = [start[0], start[1], new_pos[2]]
        out+= settings.default_pp.move_to_rapid(new_pos)
        self.tool.current_position = new_pos

        for step in range(int(self.depth/(self.tool.diameter/2.0))+1):
            for e in self.offset_path:
                out += self.process_el_to_gcode(e, step)

        new_pos = [new_pos[0], new_pos[1], self.tool.default_height]
        out+= settings.default_pp.move_to_rapid(new_pos)
        self.tool.current_position = new_pos
        return out

    def __repr__(self):
        return "<Exact follow>"
