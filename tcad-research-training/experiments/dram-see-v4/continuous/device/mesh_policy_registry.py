"""Fixed mesh-policy dispatch. Never reinterpret an archived producer as current."""
import json
import mesh_policy as r1
import mesh_policy_v2 as r2
import mesh_policy_v3 as r3
import mesh_policy_v4 as r4
import mesh_policy_v5 as r5
import mesh_policy_v6 as r6

FILES = r1.FILES
VERSIONS = {r1.POLICY_ID:r1,r2.POLICY_ID:r2,r3.POLICY_ID:r3,r4.POLICY_ID:r4,r5.POLICY_ID:r5,r6.POLICY_ID:r6}


def select(policy_id):
    if policy_id not in VERSIONS:
        raise ValueError('Unknown explicit mesh policy: '+str(policy_id))
    return VERSIONS[policy_id]


def build(policy_id, model_raw, description, scale):
    return select(policy_id).build(model_raw,description,scale)


def describe(description, policy, raw):
    return select(policy['policy_id']).describe(description,policy,raw)


def apply(text, policy):
    return select(policy['policy_id']).apply(text,policy)


def inherit(producer_inputs):
    if 'mesh-policy.json' not in producer_inputs:
        return r1.inherit(producer_inputs)
    return select(json.loads(producer_inputs['mesh-policy.json'])['policy_id']).inherit(producer_inputs)
