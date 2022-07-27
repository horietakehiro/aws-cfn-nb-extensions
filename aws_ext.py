from pyrsistent import v
import yaml
import json
import re
import logging
import sys
from abc import ABC, abstractmethod
from time import sleep
import boto3 
from cfn_flip import flip, to_yaml, to_json
import ipywidgets as widgets
from IPython.core.magic import Magics, line_magic, magics_class
from IPython.display import display

import os
from logging import getLogger, StreamHandler, DEBUG, INFO, Formatter, FileHandler
APP_BASE_DIR=os.path.join(os.environ["HOME"], ".aws-cfn-nb-extensions")
LOG_BASE_DIR=os.path.join(APP_BASE_DIR, "log")
HTML_BASE_DIR=os.path.join(APP_BASE_DIR, "html")
os.makedirs(LOG_BASE_DIR, exist_ok=True)
os.makedirs(HTML_BASE_DIR, exist_ok=True)

verbose = True
logger = getLogger(__file__)
handler = FileHandler(os.path.join(LOG_BASE_DIR, "aws-cfn-nb-extensions.log"))
if verbose:
    handler.setLevel(DEBUG)
else:
    handler.setLevel(INFO)
handler.setFormatter(Formatter("%(asctime)s %(name)s:%(lineno)s %(funcName)s [%(levelname)s]: %(message)s"))
logger.addHandler(handler)
logger.setLevel(DEBUG)
logger.propagate = False



def name_tag_getter():
    vpcs = dict()
    instances = dict()
    subnets = dict()
    volumes = dict()
    def get_name_tag(tags, default:str=""):
        name = [tag["Value"] for tag in tags if tag["Key"] == "Name"]
        try:
            return name[0]
        except IndexError:
            return default

    def get_vpc_name(vpc_id:str, client:boto3.client) -> str:
        try:
            return vpcs[vpc_id]
        except KeyError:
            resp = client.describe_vpcs()
            for vpc in resp["Vpcs"]:
                vid = vpc["VpcId"]
                try:
                    tags = vpc["Tags"]
                except KeyError:
                    vpcs[vid] = vid
                    continue
                vpcs[vid] = get_name_tag(tags, vid)

            return vpcs[vpc_id]

    def get_instance_name(instance_id:str, client:boto3.client) -> str:
        try:
            return instances[instance_id]
        except KeyError:
            resp = client.describe_instances()
            for reservation in resp["Reservations"]:
                for instance in reservation["Instances"]:
                    iid = instance["InstanceId"]
                    try:
                        tags = instance["Tags"]
                    except KeyError:
                        instance[iid] = iid
                        continue
                    instances[iid] = get_name_tag(tags, iid)

            return instances[instance_id]
    def get_subnet_name(subnet_id:str, client:boto3.client) -> str:
        try:
            return subnets[subnet_id]
        except KeyError:
            resp = client.describe_subnets()
            for subnet in resp["Subnets"]:
                sid = subnet["SubnetId"]
                try:
                    tags = subnet["Tags"]
                except KeyError:
                    subnets[sid] = sid
                    continue
                subnets[sid] = get_name_tag(tags, sid)

            return subnets[subnet_id]
    def get_volume_name(volume_id:str, client:boto3.client) -> str:
        try:
            return volumes[volume_id]
        except KeyError:
            resp = client.describe_volumes()
            for volume in resp["Volumes"]:
                vid = volume["VolumeId"]
                try:
                    tags = volume["Tags"]
                except KeyError:
                    volumes[vid] = vid
                    continue
                volumes[vid] = get_name_tag(tags, vid)
            return volumes[volume_id]

    return get_vpc_name, get_subnet_name, get_instance_name, get_volume_name

get_vpc_name, get_subnet_name, get_instance_name, get_volume_name = name_tag_getter()

def instance_name_getter():
    vpcs = dict()
    def get_vpc_name(vpc_id:str, client:boto3.client) -> str:
        try:
            return vpcs[vpc_id]
        except KeyError:
            resp = client.describe_vpcs()
            for vpc in resp["Vpcs"]:
                try:
                    tags = vpc["Tags"]
                except KeyError:
                    vpcs[vpc["VpcId"]] = vpc["VpcId"]
                    continue
                name = [tag["Value"] for tag in tags if tag["Key"] == "Name"]
                try:
                    vpcs[vpc["VpcId"]] = name[0]
                except IndexError:
                    vpcs[vpc["VpcId"]] = vpc["VpcId"]

            return vpcs[vpc_id]
    return get_vpc_name
get_vpc_name = vpc_name_getter()


class BaseAwsParameter(ABC):

    def __init__(self, param_name:str, param_def:dict) -> None:
        self.name = param_name
        self.param_def = param_def

        self.type = param_def["Type"]
        self.description = param_def.get("Description", "")
        self.default_value = param_def.get("Default", None)
        self.allowed_values = param_def.get("AllowedValues", [])
        self.allowed_pattern = param_def.get("AllowedPattern", ".*")
        self.constraint_description = param_def.get("ConstraintDescription", None)
        self.max_value = int(param_def.get("MaxLength", sys.maxsize))
        self.min_value = int(param_def.get("MinLength", 0))
        self.max_length = int(param_def.get("MaxLength", sys.maxsize))
        self.min_length = int(param_def.get("MinLength", 0))
        self.no_echo = bool(param_def.get("NoEcho", False))

        self.common_style = {'description_width': '400px'}
        self.common_layout = {"width": "auto"}

        self.description_fmt = "{name} ({description})"
        self.disabled = False

        self.widget = None

        self._create_widget()

    @abstractmethod
    def validate(self):
        pass

    @abstractmethod
    def _create_widget(self):
        pass

    @abstractmethod
    def get_value(self):
        pass


    def update_state(self, state:bool):
        self.widget.disabled = state

class StringParameter(BaseAwsParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        super().__init__(param_name, param_def)

    def _create_widget(self):
        pattern = self.allowed_pattern if self.allowed_pattern != ".*" else ""
        kwargs = dict(
            description=self.description_fmt.format(
                name=self.name, description=self.description,
            ),
            value=self.default_value,
            style=self.common_style,
            layout=self.common_layout,
            disabled=self.disabled,
            placeholder=pattern,
        )
        if len(self.allowed_values) > 0:
            kwargs["options"] = self.allowed_values
            w = widgets.Dropdown
        elif self.no_echo:
            w = widgets.Password
        else:
            w = widgets.Text

        self.widget = w(**kwargs)

    def validate(self):
        val = self.widget.value
        name = self.name
        pattern = self.allowed_pattern if self.constraint_description is None else self.constraint_description

        assert bool(val), f"{name} is empty"
        assert len(val) <= self.max_length, f"{name}'s length must be smaller equal than {self.max_length}"
        assert len(val) >= self.min_length, f"{name}'s length must be greater equal than {self.min_length}"
        assert re.match(self.allowed_pattern, val), f"{name} must match the pattern : {pattern}"

    def get_value(self):
        return self.widget.value

class MultipleStringParameter(BaseAwsParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        super().__init__(param_name, param_def)

    def _create_widget(self):
        if self.default_value is None:
            value = []
        else:
            value = self.default_value
        kwargs = dict(
            description=self.description_fmt.format(
                name=self.name, description=self.description,
            ),
            value=value,
            style=self.common_style,
            layout=self.common_layout,
            disabled=self.disabled,
            options=self.allowed_values,
        )

        self.widget = widgets.SelectMultiple(**kwargs)

    def validate(self):
        val = self.widget.value
        name = self.name

        assert len(val) != 0, f"{name} is empty"

    def get_value(self):
        return ",".join(self.widget.value)

class NumberParameter(BaseAwsParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        super().__init__(param_name, param_def)


    def _create_widget(self):
        kwargs = dict(
            description=self.description_fmt.format(
                name=self.name, description=self.description,
            ),
            value=self.default_value,
            style=self.common_style,
            layout=self.common_layout,
            disabled=self.disabled,
        )
        if len(self.allowed_values) > 0:
            kwargs["options"] = self.allowed_values
            w = widgets.Dropdown
        else:
            w = widgets.BoundedFloatText

        self.widget = w(**kwargs)

    def validate(self):
        val = self.widget.value
        name = self.name

        assert val is not None, f"{name} is empty"
        assert val <= self.max_value, f"{name}'s value must be smaller equal than {self.max_value}"
        assert val >= self.min_value, f"{name}'s value must be greater equal than {self.min_value}"

    def get_value(self):
        return str(self.widget.value)


class CdlParameter(BaseAwsParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        super().__init__(param_name, param_def)

    def _create_widget(self):
        kwargs = dict(
            description=self.description_fmt.format(
                name=self.name, description=self.description,
            ),
            value=self.default_value,
            placeholder="seperate values with ','",
            style=self.common_style,
            layout=self.common_layout,
            disabled=self.disabled,
        )
        self.widget = widgets.Text(**kwargs)

    def validate(self):
        val = self.widget.value
        name = self.name

        assert val is not None, f"{name} is empty"

    def get_value(self):
        return self.widget.value


class ListNumberParameter(BaseAwsParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        super().__init__(param_name, param_def)

    def _create_widget(self):
        kwargs = dict(
            description=self.description_fmt.format(
                name=self.name, description=self.description,
            ),
            value=self.default_value,
            placeholder="seperate values with ','",
            style=self.common_style,
            layout=self.common_layout,
            disabled=self.disabled,
        )
        self.widget = widgets.Text(**kwargs)

    def validate(self):
        val = self.widget.value
        name = self.name

        assert val is not None, f"{name} is empty"
        try:
            _ = [float(v) for v in val.split(",")]
        except ValueError:
            raise AssertionError(f"{name} must be list of numbers")

    def get_value(self):
        return self.widget.value

class AwsAzParameters(StringParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        self.client = boto3.client("ec2")        
        param_def["AllowedValues"] = self._get_allowed_value_from_aws()

        super().__init__(param_name, param_def)

    def _get_allowed_value_from_aws(self):
        # get available availability zones
        response = self.client.describe_availability_zones(
            Filters=[{"Name": "state", "Values": ["available"]}]
        )
        return [az["ZoneName"] for az in response["AvailabilityZones"]]

class AwsAzListParameter(MultipleStringParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        self.client = boto3.client("ec2")        
        param_def["AllowedValues"] = self._get_allowed_value_from_aws()
        super().__init__(param_name, param_def)

    def _get_allowed_value_from_aws(self):
        # get available availability zones
        response = self.client.describe_availability_zones(
            Filters=[{"Name": "state", "Values": ["available"]}]
        )
        return [az["ZoneName"] for az in response["AvailabilityZones"]]


class AwsSsmNameParameters(StringParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        self.client = boto3.client("ssm")        
        param_def["AllowedValues"] = self._get_allowed_value_from_aws()

        super().__init__(param_name, param_def)

    def _get_allowed_value_from_aws(self):
        # get available availability zones
        response = self.client.describe_parameters()
        return [param["Name"] for param in response["Parameters"]]


class AwsSsmValueParameters(StringParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        self.client = boto3.client("ssm")        
        param_def["AllowedValues"] = self._get_allowed_value_from_aws()

        super().__init__(param_name, param_def)

    def _get_allowed_value_from_aws(self):
        response = self.client.describe_parameters(Filters=[
            {"Key" : "Type", "Values": ["String"]}
        ])
        response = self.client.get_parameters(
            Names=[param["Name"] for param in response["Parameters"]],
        )
        return [f"{param['Name']} | {param['Value']}" for param in response["Parameters"]]

    def get_value(self):
        return self.widget.value.split(" | ")[0]

class AwsSsmValueListParameters(StringParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        self.client = boto3.client("ssm")        
        param_def["AllowedValues"] = self._get_allowed_value_from_aws()

        super().__init__(param_name, param_def)

    def _get_allowed_value_from_aws(self):
        response = self.client.describe_parameters(Filters=[
            {"Key" : "Type", "Values": ["StringList"]}
        ])
        response = self.client.get_parameters(
            Names=[param["Name"] for param in response["Parameters"]],
        )
        return [f"{param['Name']} | {param['Value']}" for param in response["Parameters"]]

    def get_value(self):
        return self.widget.value.split(" | ")[0]


class AwsSsmValueCdlParameters(StringParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        self.client = boto3.client("ssm")        
        param_def["AllowedValues"] = self._get_allowed_value_from_aws()

        super().__init__(param_name, param_def)

    def _get_allowed_value_from_aws(self):
        response = self.client.describe_parameters(Filters=[
            {"Key" : "Type", "Values": ["StringList"]}
        ])
        response = self.client.get_parameters(
            Names=[param["Name"] for param in response["Parameters"]],
        )
        return [f"{param['Name']} | {param['Value']}" for param in response["Parameters"]]

    def get_value(self):
        return self.widget.value.split(" | ")[0]


class AwsAmiParameter(StringParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        # self.client = boto3.client("ec2")        
        # param_def["AllowedValues"] = self._get_allowed_value_from_aws()
        param_def["AllowedPattern"] = "(^ami-[0-9a-z]{17}$)|(^ami-[0-9a-z]{8}$)"
        super().__init__(param_name, param_def)


class AwsInstanceIdParameter(StringParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        self.client = boto3.client("ec2")        
        param_def["AllowedValues"] = self._get_allowed_value_from_aws()
        super().__init__(param_name, param_def)

    def _get_allowed_value_from_aws(self):
        response = self.client.describe_instances()
        return [f"{instance['InstanceId']} | {get_instance_name(instance['InstanceId'], self.client)}"
            for reservation in response["Reservations"]
            for instance in reservation["Instances"]
        ]
    def get_value(self):
        return self.widget.value.split(" | ")[0]

class AwsKeyNameParameter(StringParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        self.client = boto3.client("ec2")        
        param_def["AllowedValues"] = self._get_allowed_value_from_aws()
        super().__init__(param_name, param_def)

    def _get_allowed_value_from_aws(self):
        response = self.client.describe_key_pairs()
        return [key["KeyName"] for key in response["KeyPairs"]]

class AwsSecurityGroupNameParameter(StringParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        self.client = boto3.client("ec2")        
        param_def["AllowedValues"] = self._get_allowed_value_from_aws()
        super().__init__(param_name, param_def)

    def _get_allowed_value_from_aws(self):
        response = self.client.describe_security_groups()
        return [
            f"{sg['GroupName']} | {get_vpc_name(sg['VpcId'], self.client)}"
            for sg in response["SecurityGroups"]
        ]
    def get_value(self):
        return self.widget.value.split(" | ")[0]

class AwsSecurityGroupIdParameter(StringParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        self.client = boto3.client("ec2")        
        param_def["AllowedValues"] = self._get_allowed_value_from_aws()
        super().__init__(param_name, param_def)

    def _get_allowed_value_from_aws(self):
        response = self.client.describe_security_groups()
        return [
            f"{sg['GroupId']}({sg['GroupName']}) | {get_vpc_name(sg['VpcId'], self.client)}"
            for sg in response["SecurityGroups"]
        ]

    def get_value(self):
        return self.widget.value.split("(")[0]

class AwsVolumeIdParameter(StringParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        self.client = boto3.client("ec2")        
        param_def["AllowedValues"] = self._get_allowed_value_from_aws()
        super().__init__(param_name, param_def)

    def _get_allowed_value_from_aws(self):
        response = self.client.describe_volumes()
        return [
            f"{volume['VolumeId']} | {get_volume_name(volume['VolumeId'], self.client)}"
            for volume in response["Volumes"]
        ]
    def get_value(self):
        return self.widget.value.split(" | ")[0]

class AwsSubnetIdParameter(StringParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        self.client = boto3.client("ec2")        
        param_def["AllowedValues"] = self._get_allowed_value_from_aws()
        super().__init__(param_name, param_def)

    def _get_allowed_value_from_aws(self):
        response = self.client.describe_subnets()
        return [
            f"{subnet['SubnetId']}({get_subnet_name(subnet['SubnetId'], self.client)}) | {get_vpc_name(subnet['VpcId'], self.client)}"
            for subnet in response["Subnets"]
        ]

    def get_value(self):
        return self.widget.value.split("(")[0]

class AwsVpcIdParameter(StringParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        self.client = boto3.client("ec2")        
        param_def["AllowedValues"] = self._get_allowed_value_from_aws()
        super().__init__(param_name, param_def)

    def _get_allowed_value_from_aws(self):
        response = self.client.describe_vpcs()
        return [
            f"{vpc['VpcId']} | {get_vpc_name(vpc['VpcId'], self.client)}"
            for vpc in response["Vpcs"]
        ]

    def get_value(self):
        return self.widget.value.split(" | ")[0]

class AwsHostedZoneIdParameter(StringParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        self.client = boto3.client("route53")        
        param_def["AllowedValues"] = self._get_allowed_value_from_aws()
        super().__init__(param_name, param_def)

    def _get_allowed_value_from_aws(self):
        response = self.client.list_hosted_zones()
        return [
            f"{zone['Id'].split('/')[-1]} | {zone['Name']}"
            for zone in response["HostedZones"]
        ]

    def get_value(self):
        return self.widget.value.split(" | ")[0]

class AwsAzNameListParameter(MultipleStringParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        param_def["AllowedValues"] = AwsAzParameters(param_name, param_def).allowed_values
        super().__init__(param_name, param_def)

class AwsAmiIdListParameter(CdlParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        param_def["AllowedPattern"] = AwsAmiParameter(param_name, param_def).allowed_pattern
        super().__init__(param_name, param_def)
    def validate(self):
        for val in self.widget.value.split(","):
            assert re.match(self.allowed_pattern, val), f"{val} must be a form of {self.allowed_pattern}"
        return super().validate()

class AwsInstanceIdListParameter(MultipleStringParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        param_def["AllowedValues"] = AwsInstanceIdParameter(param_name, param_def).allowed_values
        super().__init__(param_name, param_def)

    def get_value(self):
        return ",".join([v.split(" | ")[0] for v in self.widget.value])

class AwsSecurityGroupNameListParameter(MultipleStringParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        param_def["AllowedValues"] = AwsSecurityGroupNameParameter(param_name, param_def).allowed_values
        super().__init__(param_name, param_def)

    def get_value(self):
        return ",".join([v.split(" | ")[0] for v in self.widget.value])

class AwsSecurityGroupIdListParameter(MultipleStringParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        param_def["AllowedValues"] = AwsSecurityGroupIdParameter(param_name, param_def).allowed_values
        super().__init__(param_name, param_def)

    def get_value(self):
        return ",".join([v.split("(")[0] for v in self.widget.value])

class AwsSubnetIdListParameter(MultipleStringParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        param_def["AllowedValues"] = AwsSubnetIdParameter(param_name, param_def).allowed_values
        super().__init__(param_name, param_def)

    def get_value(self):
        return ",".join([v.split("(")[0] for v in self.widget.value])

class AwsVolumeIdListParameter(MultipleStringParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        param_def["AllowedValues"] = AwsVolumeIdParameter(param_name, param_def).allowed_values
        super().__init__(param_name, param_def)

    def get_value(self):
        return ",".join([v.split(" | ")[0] for v in self.widget.value])

class AwsVpcIdListParameter(MultipleStringParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        param_def["AllowedValues"] = AwsVpcIdParameter(param_name, param_def).allowed_values
        super().__init__(param_name, param_def)

    def get_value(self):
        return ",".join([v.split(" | ")[0] for v in self.widget.value])

class AwsHostedZoneIdListParameter(MultipleStringParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        param_def["AllowedValues"] = AwsHostedZoneIdParameter(param_name, param_def).allowed_values
        super().__init__(param_name, param_def)

    def get_value(self):
        return ",".join([v.split(" | ")[0] for v in self.widget.value])


class AwsSsmSpecificParameters(StringParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        self.client = boto3.client("ssm")
        self.param_def = param_def
        self.type = param_def["Type"]
        self.name = param_name
        param_def["AllowedValues"] = self._get_allowed_value_from_aws()

        super().__init__(param_name, param_def)

    def _get_allowed_value_from_aws(self):
        response = self.client.describe_parameters(Filters=[
            {"Key" : "Type", "Values": ["String"]}
        ])
        response = self.client.get_parameters(
            Names=[param["Name"] for param in response["Parameters"]],
        )
        aws_type = self.type[len("AWS::SSM::Parameter::Value<"):-1]
        allowed_values = AwsExtension.parameter_widgets[aws_type](self.name, self.param_def).allowed_values
        allowed_values = [val.split(" | ")[0].split("(")[0] for val in allowed_values]
        return [
            f"{param['Name']} | {param['Value']}" for param in response["Parameters"]
            if param["Value"] in allowed_values
        ]
    def get_value(self):
        return self.widget.value.split(" | ")[0]

class AwsSsmSpecificListParameters(StringParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        self.client = boto3.client("ssm")
        self.param_def = param_def
        self.type = param_def["Type"]
        self.name = param_name
        param_def["AllowedValues"] = self._get_allowed_value_from_aws()

        super().__init__(param_name, param_def)

    def _get_allowed_value_from_aws(self):
        response = self.client.describe_parameters(Filters=[
            {"Key" : "Type", "Values": ["StringList"]}
        ])
        response = self.client.get_parameters(
            Names=[param["Name"] for param in response["Parameters"]],
        )
        aws_type = self.type[len("AWS::SSM::Parameter::Value<"):-1]
        allowed_values = AwsExtension.parameter_widgets[aws_type](self.name, self.param_def).allowed_values
        allowed_values = [val.split(" | ")[0].split("(")[0] for val in allowed_values]
        return [
            f"{param['Name']} | {param['Value']}" for param in response["Parameters"]
            if set(param["Value"].split(",")) < set(allowed_values)
        ]
    def get_value(self):
        return self.widget.value.split(" | ")[0]


class AwsSsmListSpecificParameters(StringParameter):
    def __init__(self, param_name: str, param_def: dict) -> None:
        self.client = boto3.client("ssm")
        self.param_def = param_def
        self.type = param_def["Type"]
        self.name = param_name
        param_def["AllowedValues"] = self._get_allowed_value_from_aws()

        super().__init__(param_name, param_def)

    def _get_allowed_value_from_aws(self):
        response = self.client.describe_parameters(Filters=[
            {"Key" : "Type", "Values": ["String"]}
        ])
        response = self.client.get_parameters(
            Names=[param["Name"] for param in response["Parameters"]],
        )
        aws_type = self.type[len("AWS::SSM::Parameter::Value<"):-1]
        allowed_values = AwsExtension.parameter_widgets[aws_type](self.name, self.param_def).allowed_values
        allowed_values = [val.split(" | ")[0].split("(")[0] for val in allowed_values]
        return [
            f"{param['Name']} | {param['Value']}" for param in response["Parameters"]
            if param["Value"] in allowed_values
        ]
    def get_value(self):
        return self.widget.value.split(" | ")[0]


@magics_class
class AwsExtension(Magics):

    parameter_widgets = {
        "String": StringParameter,
        "Number": NumberParameter,
        "CommaDelimitedList": CdlParameter,
        "List<Number>": ListNumberParameter,
        "AWS::EC2::AvailabilityZone::Name": AwsAzParameters,
        "List<AWS::EC2::AvailabilityZone::Name>": AwsAzListParameter,
        "AWS::SSM::Parameter::Name": AwsSsmNameParameters,
        "AWS::SSM::Parameter::Value<String>": AwsSsmValueParameters,
        "AWS::SSM::Parameter::Value<List<String>>": AwsSsmValueListParameters,
        "AWS::SSM::Parameter::Value<CommaDelimitedList>": AwsSsmValueListParameters,
        "AWS::EC2::Image::Id": AwsAmiParameter,
        "AWS::EC2::Instance::Id": AwsInstanceIdParameter,
        "AWS::EC2::KeyPair::KeyName": AwsKeyNameParameter,
        "AWS::EC2::SecurityGroup::GroupName": AwsSecurityGroupNameParameter,
        "AWS::EC2::SecurityGroup::Id": AwsSecurityGroupIdParameter,
        "AWS::EC2::Subnet::Id": AwsSubnetIdParameter,
        "AWS::EC2::VPC::Id": AwsVpcIdParameter,
        "AWS::Route53::HostedZone::Id": AwsHostedZoneIdParameter,
        "List<AWS::EC2::AvailabilityZone::Name>": AwsAzNameListParameter,
        "List<AWS::EC2::Image::Id>": AwsAmiIdListParameter,
        "List<AWS::EC2::Instance::Id>": AwsInstanceIdListParameter,
        "List<AWS::EC2::SecurityGroup::GroupName>": AwsSecurityGroupNameListParameter,
        "List<AWS::EC2::SecurityGroup::Id>": AwsSecurityGroupIdListParameter,
        "List<AWS::EC2::Subnet::Id>": AwsSubnetIdListParameter,
        "AWS::EC2::Volume::Id": AwsVolumeIdParameter,
        "List<AWS::EC2::Volume::Id>": AwsVolumeIdListParameter,
        "List<AWS::EC2::VPC::Id>": AwsVpcIdListParameter,
        "List<AWS::Route53::HostedZone::Id>": AwsHostedZoneIdListParameter,
        "AWS::SSM::Parameter::Value<AWS::EC2::AvailabilityZone::Name>": AwsSsmSpecificParameters,
        "AWS::SSM::Parameter::Value<AWS::EC2::Image::Id>": AwsSsmSpecificParameters,
        "AWS::SSM::Parameter::Value<AWS::EC2::Instance::Id>": AwsSsmSpecificParameters,
        "AWS::SSM::Parameter::Value<AWS::EC2::KeyPair::KeyName>": AwsSsmSpecificParameters,
        "AWS::SSM::Parameter::Value<AWS::EC2::SecurityGroup::GroupName>": AwsSsmSpecificParameters,
        "AWS::SSM::Parameter::Value<AWS::EC2::SecurityGroup::Id>": AwsSsmSpecificParameters,
        "AWS::SSM::Parameter::Value<AWS::EC2::Subnet::Id>": AwsSsmSpecificParameters,
        "AWS::SSM::Parameter::Value<AWS::EC2::Volume::Id>": AwsSsmSpecificParameters,
        "AWS::SSM::Parameter::Value<AWS::EC2::VPC::Id>": AwsSsmSpecificParameters,
        "AWS::SSM::Parameter::Value<AWS::Route53::HostedZone::Id>": AwsSsmSpecificParameters,

        "AWS::SSM::Parameter::Value<List<AWS::EC2::AvailabilityZone::Name>>": AwsSsmSpecificListParameters,
        "AWS::SSM::Parameter::Value<List<AWS::EC2::Image::Id>>": AwsSsmSpecificListParameters,
        "AWS::SSM::Parameter::Value<List<AWS::EC2::Instance::Id>>": AwsSsmSpecificListParameters,
        "AWS::SSM::Parameter::Value<List<AWS::EC2::KeyPair::KeyName>>": AwsSsmSpecificListParameters,
        "AWS::SSM::Parameter::Value<List<AWS::EC2::SecurityGroup::GroupName>>": AwsSsmSpecificListParameters,
        "AWS::SSM::Parameter::Value<List<AWS::EC2::SecurityGroup::Id>>": AwsSsmSpecificListParameters,
        "AWS::SSM::Parameter::Value<List<AWS::EC2::Subnet::Id>>": AwsSsmSpecificListParameters,
        "AWS::SSM::Parameter::Value<List<AWS::EC2::Volume::Id>>": AwsSsmSpecificListParameters,
        "AWS::SSM::Parameter::Value<List<AWS::EC2::VPC::Id>>": AwsSsmSpecificListParameters,
        "AWS::SSM::Parameter::Value<List<AWS::Route53::HostedZone::Id>>": AwsSsmSpecificListParameters,

        # "AWS::SSM::Parameter::Value<List<List<AWS::EC2::AvailabilityZone::Name>>>": ,

    }
    
    def __init__(self, shell=None, **kwargs):
        self.template_path = None
        self.parameter_path = None

        self.parameter_vals = dict()


        self.common_style = {'description_width': '250px'}
        self.common_layout = {"width": "auto"}

        self.description_fmt = "{name} ({description})"
        self.disabled = False


        super().__init__(shell, **kwargs)


    @line_magic
    def set_cfn_parameters(self, line):
        """
        args:
            - template_path: path to ARM template json file in which parameter definitions written
            - parameter_path: path to parameter json file for saving actual parameter values for ARM template
                - if not specified, the default path is `{template_path's dir}/{template_path's basename}.parameters.json`
        - load parameters definitions from ARM template file
        - display widgets for setting each parameter values and save button
        - when save button pushed, validate parameter values and save them as parameter file
        """

        line = line.split()
        template_path = line[0]
        try:
            parameter_path = line[1]
        except IndexError:
            parameter_path = None

        logger.debug(f"template_path: {template_path}")
        logger.debug(f"parameter_path: {parameter_path}")
        self.template_path = template_path
        self.parameter_path = parameter_path

        if self.parameter_path is None:
            self.parameter_path = self.template_path.rsplit(
                ".", maxsplit=1
            )[0] + ".parameters.json"

        # load ARM template and parameters section in it
        with open(template_path, "r", encoding="utf-8") as fp:
            if template_path.split(".")[-1] != "json":
                template = to_json(fp.read())
            template = json.loads(template)
        parameter_defs = template["Parameters"]
        logger.debug(f"loaded parameter definitions : {parameter_defs}")

        # initialize widgets for each parameters
        for param_name, param_def in parameter_defs.items():
            p = self.parameter_widgets[param_def["Type"]](param_name, param_def)
            self.parameter_vals[param_name] = p
            # print(p)
            display(p.widget)

        display(self._save_widget())

   


    def _save_widget(self) -> widgets.Widget:
        w = widgets.Button(
            value=self.disabled,
            description='save',
            disabled=False,
            style=self.common_style,
            layout=self.common_layout,
            button_style='success', # 'success', 'info', 'warning', 'danger' or ''
            tooltip='Click here if you want to save parameter values',
            icon='check' # (FontAwesome names without the `fa-` prefix)
        )

        def on_button_click(b):
            output = widgets.Output()
            display(output)

            try:
                for v in self.parameter_vals.values():
                    v.validate()
            except AssertionError as ex:
                with output:
                    print(f"parameter validation error! : {ex}", file=sys.stderr)
                    sleep(5)
                    output.clear_output()
                return

            # if all validation passes, freeze parameter values and save in them in files
            for v in self.parameter_vals.values():
                v.update_state(True)
            self._save_parameters_as_file()
            with output:
                print(f"successfully save parameters in {self.parameter_path}!")
                sleep(5)
                output.clear_output()


        w.on_click(on_button_click)
        return w

    def _save_parameters_as_file(self):


        parameters_file_body = dict(Parameters={})
        for k, v in self.parameter_vals.items():
            parameters_file_body["Parameters"][k] = v.get_value()
        
        with open(self.parameter_path, "w", encoding="utf-8") as fp:
            json.dump(parameters_file_body, fp, indent=4)




def load_ipython_extension(ipython):
    ipython.register_magics(AwsExtension)

