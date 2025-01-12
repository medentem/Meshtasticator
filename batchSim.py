#!/usr/bin/env python3
import matplotlib

try:
    matplotlib.use("TkAgg")
except ImportError:
    print('Tkinter is needed. Install python3-tk with your package manager.')
    exit(1)

import simpy
import numpy as np
import random
import matplotlib.pyplot as plt

from lib.common import *
from lib.packet import *
from lib.mac import *
from lib.discrete_event import *
from lib.node import *

VERBOSE = False
SAVE = True

if VERBOSE:
    def verboseprint(*args, **kwargs): 
        print(*args, **kwargs)
else:
    def verboseprint(*args, **kwargs): 
        pass

###########################################################
# Progress-logging process
###########################################################
def simulationProgress(env, currentRep, repetitions, end_time):
    """
    Periodically prints the fraction of simulation time elapsed,
    overwriting the same line each time.
    """
    while True:
        fraction = env.now / end_time
        # Overwrite the same line with \r, flush so it appears immediately
        print(f"\rSimulation {currentRep+1} of {repetitions} progress: {fraction*100:.1f}% ", end="", flush=True)
        if env.now >= end_time:
            break
        yield env.timeout(1) 

# Add your router types here
routerTypes = [conf.ROUTER_TYPE.MANAGED_FLOOD, conf.ROUTER_TYPE.BLOOM]

repetitions = 3
numberOfNodes = [3, 15, 25, 30, 40, 50, 80, 100, 150, 200]

# We will collect the metrics in dictionaries keyed by router type.
# For example: collisions_dict[ routerType ] = [list of mean collisions, one per nrNodes]
collisions_dict = {}
collisionStds_dict = {}
meanDelays_dict = {}
delayStds_dict = {}
meanTxAirUtils_dict = {}
txAirUtilsStds_dict = {}
reachability_dict = {}
reachabilityStds_dict = {}
usefulness_dict = {}
usefulnessStds_dict = {}

# Coverage metrics, only used by the BLOOM router
coverageFp_dict = {}
coverageFn_dict = {}

# If you have link asymmetry metrics
asymmetricLinkRate_dict = {}
symmetricLinkRate_dict = {}
noLinkRate_dict = {}

# Initialize dictionaries for each router type
for rt in routerTypes:
    collisions_dict[rt] = []
    collisionStds_dict[rt] = []
    meanDelays_dict[rt] = []
    delayStds_dict[rt] = []
    meanTxAirUtils_dict[rt] = []
    txAirUtilsStds_dict[rt] = []
    reachability_dict[rt] = []
    reachabilityStds_dict[rt] = []
    usefulness_dict[rt] = []
    usefulnessStds_dict[rt] = []

    coverageFp_dict[rt] = []
    coverageFn_dict[rt] = []

    asymmetricLinkRate_dict[rt] = []
    symmetricLinkRate_dict[rt] = []
    noLinkRate_dict[rt] = []

###########################################################
# Main simulation loops
###########################################################

# Outer loop for each router type
for routerType in routerTypes:
    conf.SELECTED_ROUTER_TYPE = routerType
    routerTypeLabel = str(routerType)

    # Prepare arrays for the final plot data, one per metric
    collisions = []
    collisionsStds = []
    meanDelays = []
    delayStds = []
    meanTxAirUtils = []
    txAirUtilsStds = []
    reachability = []
    reachabilityStds = []
    usefulness = []
    usefulnessStds = []
    coverageFpAll = []
    coverageFnAll = []
    asymmetricLinkRateAll = []
    symmetricLinkRateAll = []
    noLinkRateAll = []

    # Inner loop for each nrNodes
    for p, nrNodes in enumerate(numberOfNodes):
            
        conf.NR_NODES = nrNodes
        conf.updateRouterDependencies()

        nodeReach = [0 for _ in range(repetitions)]
        nodeUsefulness = [0 for _ in range(repetitions)]
        collisionRate = [0 for _ in range(repetitions)]
        meanDelay = [0 for _ in range(repetitions)]
        meanTxAirUtilization = [0 for _ in range(repetitions)]
        coverageFp = [0 for _ in range(repetitions)]
        coverageFn = [0 for _ in range(repetitions)]
        asymmetricLinkRate = [0 for _ in range(repetitions)]
        symmetricLinkRate = [0 for _ in range(repetitions)]
        noLinkRate = [0 for _ in range(repetitions)]

        print(f"\n[Router: {routerTypeLabel}] Start of {p+1} out of {len(numberOfNodes)} - {nrNodes} nodes")

        for rep in range(repetitions):
            setBatch(rep)
            random.seed(rep)
            env = simpy.Environment()
            bc_pipe = BroadcastPipe(env)

            # Start the progress-logging process
            env.process(simulationProgress(env, rep, repetitions, conf.SIMTIME))

            nodes = []
            messages = []
            packets = []
            delays = []
            packetsAtN = [[] for _ in range(conf.NR_NODES)]
            messageSeq = {"val": 0}

            found = False
            while not found:
                nodes = []
                for nodeId in range(conf.NR_NODES):
                    node = MeshNode(
                        nodes, env, bc_pipe, nodeId, conf.PERIOD,
                        messages, packetsAtN, packets, delays, None,
                        messageSeq, verboseprint
                    )
                    if node.x is None:
                        break
                    nodes.append(node)
                if len(nodes) == conf.NR_NODES:
                    found = True

            totalPairs, symmetricLinks, asymmetricLinks, noLinks = setupAsymmetricLinks(nodes)

            # Start simulation
            env.run(until=conf.SIMTIME)

            # Calculate stats
            nrCollisions = sum([1 for pkt in packets for n in nodes if pkt.collidedAtN[n.nodeid]])
            nrSensed = sum([1 for pkt in packets for n in nodes if pkt.sensedByN[n.nodeid]])
            nrReceived = sum([1 for pkt in packets for n in nodes if pkt.receivedAtN[n.nodeid]])
            nrUseful = sum([n.usefulPackets for n in nodes])

            if nrSensed != 0:
                collisionRate[rep] = float(nrCollisions) / nrSensed * 100
            else:
                collisionRate[rep] = np.NaN

            if messageSeq["val"] != 0:
                nodeReach[rep] = nrUseful / (messageSeq["val"] * (conf.NR_NODES - 1)) * 100
            else:
                nodeReach[rep] = np.NaN

            if nrReceived != 0:
                nodeUsefulness[rep] = nrUseful / nrReceived * 100
            else:
                nodeUsefulness[rep] = np.NaN

            meanDelay[rep] = np.nanmean(delays)
            meanTxAirUtilization[rep] = sum([n.txAirUtilization for n in nodes]) / conf.NR_NODES

            # Coverage is only meaningful for BLOOM
            if conf.SELECTED_ROUTER_TYPE == conf.ROUTER_TYPE.BLOOM:
                potentialReceivers = len(packets) * (conf.NR_NODES - 1)
                if potentialReceivers > 0:
                    coverageFp[rep] = round(
                        sum([n.coverageFalsePositives for n in nodes]) / potentialReceivers * 100, 2
                    )
                    coverageFn[rep] = round(
                        sum([n.coverageFalseNegatives for n in nodes]) / potentialReceivers * 100, 2
                    )

            if conf.MODEL_ASYMMETRIC_LINKS:
                asymmetricLinkRate[rep] = round(asymmetricLinks / totalPairs * 100, 2)
                symmetricLinkRate[rep] = round(symmetricLinks / totalPairs * 100, 2)
                noLinkRate[rep] = round(noLinks / totalPairs * 100, 2)

        # After finishing all repetitions for this nrNodes, compute means/stdevs
        collisions.append(np.nanmean(collisionRate))
        collisionsStds.append(np.nanstd(collisionRate))
        reachability.append(np.nanmean(nodeReach))
        reachabilityStds.append(np.nanstd(nodeReach))
        usefulness.append(np.nanmean(nodeUsefulness))
        usefulnessStds.append(np.nanstd(nodeUsefulness))
        meanDelays.append(np.nanmean(meanDelay))
        delayStds.append(np.nanstd(meanDelay))
        meanTxAirUtils.append(np.nanmean(meanTxAirUtilization))
        txAirUtilsStds.append(np.nanstd(meanTxAirUtilization))
        coverageFpAll.append(np.nanmean(coverageFp))
        coverageFnAll.append(np.nanmean(coverageFn))
        asymmetricLinkRateAll.append(np.nanmean(asymmetricLinkRate))
        symmetricLinkRateAll.append(np.nanmean(symmetricLinkRate))
        noLinkRateAll.append(np.nanmean(noLinkRate))

        # Saving to file if needed
        if SAVE:
            print('Saving to file...')
            data = {
                "CollisionRate": collisionRate,
                "Reachability": nodeReach,
                "Usefulness": nodeUsefulness,
                "meanDelay": meanDelay,
                "meanTxAirUtil": meanTxAirUtilization,
                "nrCollisions": nrCollisions,
                "nrSensed": nrSensed,
                "nrReceived": nrReceived,
                "usefulPackets": nrUseful,
                "MODEM": conf.NR_NODES,
                "MODEL": conf.MODEL,
                "NR_NODES": conf.NR_NODES,
                "INTERFERENCE_LEVEL": conf.INTERFERENCE_LEVEL,
                "COLLISION_DUE_TO_INTERFERENCE": conf.COLLISION_DUE_TO_INTERFERENCE,
                "XSIZE": conf.XSIZE,
                "YSIZE": conf.YSIZE,
                "MINDIST": conf.MINDIST,
                "SIMTIME": conf.SIMTIME,
                "PERIOD": conf.PERIOD,
                "PACKETLENGTH": conf.PACKETLENGTH,
                "nrMessages": messageSeq["val"],
                "SELECTED_ROUTER_TYPE": routerTypeLabel
            }
            subdir = "hopLimit3"
            simReport(data, subdir, nrNodes)

        if conf.SELECTED_ROUTER_TYPE == conf.ROUTER_TYPE.BLOOM and conf.NR_NODES <= conf.SMALL_MESH_NUM_NODES:
            print("'Small Mesh' correction was applied to this simulation")

        # Print summary
        print('Collision rate average:', round(np.nanmean(collisionRate), 2))
        print('Reachability average:', round(np.nanmean(nodeReach), 2))
        print('Usefulness average:', round(np.nanmean(nodeUsefulness), 2))
        print('Delay average:', round(np.nanmean(meanDelay), 2))
        print('Tx air utilization average:', round(np.nanmean(meanTxAirUtilization), 2))
        if conf.SELECTED_ROUTER_TYPE == conf.ROUTER_TYPE.BLOOM:
            print("Coverage false positives:", round(np.nanmean(coverageFp), 2))
            print("Coverage false negatives:", round(np.nanmean(coverageFn), 2))
        if conf.MODEL_ASYMMETRIC_LINKS:
            print('Asymmetric Links:', round(np.nanmean(asymmetricLinkRate), 2))
            print('Symmetric Links:', round(np.nanmean(symmetricLinkRate), 2))
            print('No Links:', round(np.nanmean(noLinkRate), 2))

    # After finishing all nrNodes for the *current* router type,
    # store these lists in the dictionary so we can plot after.
    collisions_dict[routerType] = collisions
    collisionStds_dict[routerType] = collisionsStds
    reachability_dict[routerType] = reachability
    reachabilityStds_dict[routerType] = reachabilityStds
    usefulness_dict[routerType] = usefulness
    usefulnessStds_dict[routerType] = usefulnessStds
    meanDelays_dict[routerType] = meanDelays
    delayStds_dict[routerType] = delayStds
    meanTxAirUtils_dict[routerType] = meanTxAirUtils
    txAirUtilsStds_dict[routerType] = txAirUtilsStds
    coverageFp_dict[routerType] = coverageFpAll
    coverageFn_dict[routerType] = coverageFnAll
    asymmetricLinkRate_dict[routerType] = asymmetricLinkRateAll
    symmetricLinkRate_dict[routerType] = symmetricLinkRateAll
    noLinkRate_dict[routerType] = noLinkRateAll

###########################################################
# Plotting
###########################################################

def router_type_label(rt):
    if rt == conf.ROUTER_TYPE.MANAGED_FLOOD:
        return "Managed Flood"
    elif rt == conf.ROUTER_TYPE.BLOOM:
        return "Bloom"
    else:
        return str(rt)

# 1) Collision Rate
plt.figure()
for rt in routerTypes:
    plt.errorbar(
        numberOfNodes,
        collisions_dict[rt],
        collisionStds_dict[rt],
        fmt='-o', capsize=3, ecolor='red', elinewidth=0.5, capthick=0.5,
        label=router_type_label(rt)
    )
plt.xlabel('#nodes')
plt.ylabel('Collision rate (%)')
plt.legend()
plt.title('Collision Rate by Router Type')

# 2) Average Delay
plt.figure()
for rt in routerTypes:
    plt.errorbar(
        numberOfNodes,
        meanDelays_dict[rt],
        delayStds_dict[rt],
        fmt='-o', capsize=3, ecolor='red', elinewidth=0.5, capthick=0.5,
        label=router_type_label(rt)
    )
plt.xlabel('#nodes')
plt.ylabel('Average delay (ms)')
plt.legend()
plt.title('Average Delay by Router Type')

# 3) Average Tx air utilization
plt.figure()
for rt in routerTypes:
    plt.errorbar(
        numberOfNodes,
        meanTxAirUtils_dict[rt],
        txAirUtilsStds_dict[rt],
        fmt='-o', capsize=3, ecolor='red', elinewidth=0.5, capthick=0.5,
        label=router_type_label(rt)
    )
plt.xlabel('#nodes')
plt.ylabel('Average Tx air utilization (ms)')
plt.legend()
plt.title('Tx Air Utilization by Router Type')

# 4) Reachability
plt.figure()
for rt in routerTypes:
    plt.errorbar(
        numberOfNodes,
        reachability_dict[rt],
        reachabilityStds_dict[rt],
        fmt='-o', capsize=3, ecolor='red', elinewidth=0.5, capthick=0.5,
        label=router_type_label(rt)
    )
plt.xlabel('#nodes')
plt.ylabel('Reachability (%)')
plt.legend()
plt.title('Reachability by Router Type')

# 5) Usefulness
plt.figure()
for rt in routerTypes:
    plt.errorbar(
        numberOfNodes,
        usefulness_dict[rt],
        usefulnessStds_dict[rt],
        fmt='-o', capsize=3, ecolor='red', elinewidth=0.5, capthick=0.5,
        label=router_type_label(rt)
    )
plt.xlabel('#nodes')
plt.ylabel('Usefulness (%)')
plt.legend()
plt.title('Usefulness by Router Type')

plt.show()

plt.figure()
for rt in routerTypes:
    if rt == conf.ROUTER_TYPE.BLOOM:
        plt.plot(numberOfNodes, coverageFp_dict[rt], '-o', label=f"Cov False Pos: {router_type_label(rt)}")
        plt.plot(numberOfNodes, coverageFn_dict[rt], '-o', label=f"Cov False Neg: {router_type_label(rt)}")
plt.xlabel('#nodes')
plt.ylabel('Coverage rates (%)')
plt.legend()
plt.title('Coverage (Bloom Only)')
plt.show()
