from pxr import Usd, UsdGeom, Gf, UsdLux
import json
import argparse
import os
import sys
import pywavefront

created_stages = {}


def get_basename(filename):
    return os.path.basename(filename).rsplit('.')[0]


def get_usd_from_obj_name(geo_file):
    geo_usd_file_name = 'primitives/' + get_basename(geo_file) + '.usda'
    if geo_usd_file_name not in created_stages:
        parse_obj_to_usd(geo_file, geo_usd_file_name)
    return geo_usd_file_name


def parse_obj_to_usd(obj_file, usd_stage):
    geo_stage = stage.CreateNew(usd_stage)
    geo_main_prim = UsdGeom.Xform.Define(geo_stage, '/' + get_basename(obj_file))

    with open(os.path.join(data_dir, obj_file), 'r') as obj_data:
        for line in obj_data:
            if line.startswith('usemtl'):
                if len(line.split()) > 1:
                    mat = line.split()[1]
                    prim_path = geo_main_prim.GetPath().AppendChild(mat)
                    if not geo_stage.GetPrimAtPath(prim_path):
                        mesh_prim = UsdGeom.Mesh.Define(geo_stage, prim_path)
    
    geo_stage.SetDefaultPrim(geo_main_prim.GetPrim())
    geo_stage.Save()
    created_stages[usd_stage] = geo_stage


def parse_instance_json_file(json_file, stage):
    ''' Parses an instance json file and adds data to parent prim '''
    instancer = stage.DefinePrim('/Instances')
    stage.SetDefaultPrim(instancer.GetPrim())

    print("Creating instance data from " + json_file)
    with open(json_file, "r") as read_file:
        for name, instances in json.load(read_file).items():
            instance_parent = stage.DefinePrim(instancer.GetPath().AppendChild(get_basename(name)))
            proto_usd_file = get_usd_from_obj_name(name)

            for instance_name, instance_transform in instances.items():
                instance_path = instance_parent.GetPath().AppendChild(instance_name)
                instance_prim = UsdGeom.Xform.Define(stage, instance_path)
                instance_prim.GetPrim().GetReferences().AddReference(proto_usd_file)
                instance_prim.GetPrim().SetInstanceable(True)
                xform = instance_prim.AddTransformOp()
                xform.Set(Gf.Matrix4d(*instance_transform))


def create_instance(stage, sdf_path, transform, sub_instances, geo_file):
    ''' Creates a geo prim with sub instances '''
    geo_prim = UsdGeom.Xform.Define(stage, sdf_path)
    xform = geo_prim.AddTransformOp()
    xform.Set(Gf.Matrix4d(*transform))
    # make geo mesh
    if geo_file:
        geo_usd_file = get_usd_from_obj_name(geo_file)
        
        # reference to prim
        geo_prim.GetPrim().GetReferences().AddReference(geo_usd_file)
    
    if sub_instances is not None:
        for sub_instance_name, sub_instance_data in sub_instances.items():
            json_filename = os.path.join(data_dir, sub_instance_data['jsonFile'])

            # create usd stage name from json file
            instance_usd_name = os.path.relpath(json_filename, os.path.join(data_dir, 'json'))
            instance_usd_name = instance_usd_name.rsplit('.')[0] + '.usda'

            if instance_usd_name not in created_stages:
                sub_stage = stage.CreateNew(instance_usd_name)
                json_filename = os.path.join(data_dir, json_filename)
                if sub_instance_data['type'] == 'archive':
                    parse_instance_json_file(json_filename, sub_stage)
                sub_stage.Save()
                created_stages[instance_usd_name] = sub_stage

            # reference sub dir stage
            sub_prim = stage.DefinePrim(sdf_path.AppendChild(sub_instance_name))
            sub_prim.GetReferences().AddReference(instance_usd_name)


def parse_light(light_path, light_data, stage):
    # only quad and dome types
    if light_data['type'] == 'quad':
        light = UsdLux.RectLight.Define(stage, light_path)
        xform = light.AddTransformOp()
        xform.Set(Gf.Matrix4d(*light_data['translationMatrix']))
        light.CreateColorAttr().Set(Gf.Vec3f(*light_data['color'][:3]))
        light.CreateExposureAttr().Set(light_data['exposure'])
        light.CreateWidthAttr().Set(light_data['width'])
        light.CreateHeightAttr().Set(light_data['height'])
    else:
        # dome light
        light = UsdLux.DomeLight.Define(stage, light_path)
        xform = light.AddTransformOp()
        xform.Set(Gf.Matrix4d(*light_data['translationMatrix']))
        light.CreateColorAttr().Set(Gf.Vec3f(*light_data['color'][:3]))
        light.CreateExposureAttr().Set(light_data['exposure'])
        # TODO textures


def parse_json_file(json_file, stage):
    ''' Parses a json file and adds data to parent prim '''
    with open(json_file, "r") as read_file:
        print("Parsing " + json_file)
        data = json.load(read_file)

        # Create root prim for this stage
        if 'name' in data:
            sdf_path = '/' + data['name']
        else:
            sdf_path = '/lights'
        root_prim = stage.DefinePrim(sdf_path, 'Xform')
        stage.SetDefaultPrim(root_prim)

        if 'name' in data:
            # geo type file
            
            # Create main prim
            instance_primitives = data.get('instancedPrimitiveJsonFiles', None)
            create_instance(stage, root_prim.GetPath().AppendChild(data['name']), data['transformMatrix'],
                            instance_primitives, data['geomObjFile'])
            
            # instanced copies
            if 'instancedCopies' in data:
                for instance_name, instance_data in data['instancedCopies'].items():
                    create_instance(stage, root_prim.GetPath().AppendChild(instance_name),
                                    instance_data['transformMatrix'],
                                    instance_data.get('instancedPrimitiveJsonFiles',
                                                      instance_primitives),
                                    instance_data.get('geomObjFile', data['geomObjFile']))

        elif 'lights' in json_file:
            # lights type file
            for light_name, light_data in data.items():
                parse_light(root_prim.GetPath().AppendChild(light_name), light_data, stage)

            

        return


parser = argparse.ArgumentParser(description='Converts Moana Island Dataset to USD with similar directory structure')
parser.add_argument('data_dir', help='Directory where Moana data is')
parser.add_argument('out_dir', help='Output directory')

args = parser.parse_args()

out_dir = args.out_dir
if not os.path.exists(out_dir):
    os.makedirs(out_dir)
data_dir = os.path.abspath(args.data_dir)

# change to out directory to make new stages easier to make
os.chdir(out_dir)
out_file = 'MoanaIsland.usda'
stage = Usd.Stage.CreateNew(out_file)
root_path = '/Moana_Island'
island_prim = stage.DefinePrim(root_path)

print("Parsing Moana Island Data at " + data_dir)
if 'json' not in os.listdir(data_dir):
    print("Error!!! " + data_dir + " does not have json dir")
    sys.exit()

for sub_dir in os.listdir(os.path.join(data_dir,'json')):
    if sub_dir.startswith('.') or sub_dir == 'cameras':
        continue

    if not os.path.exists(sub_dir):
        os.makedirs(sub_dir) 
    new_file = sub_dir + '.usda'
    
    # make sub dir USD stage
    sub_usd_stage = Usd.Stage.CreateNew(os.path.join(sub_dir, new_file))
    parse_json_file(os.path.join(data_dir, 'json', sub_dir, sub_dir + '.json'), sub_usd_stage)
    sub_usd_stage.GetRootLayer().Save()

    # reference sub dir stage
    sub_prim = stage.DefinePrim(island_prim.GetPath().AppendChild(sub_dir))
    sub_prim.GetReferences().AddReference('./' + sub_dir + '/' + str(new_file))


stage.GetRootLayer().Save()