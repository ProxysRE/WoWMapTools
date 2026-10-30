"""Declared M2 effects: capability warnings, never a substitute for visual review."""
import struct


def effect_features(data):
    if len(data)<160 or data[:4]!=b'MD20' or struct.unpack_from('<I',data,4)[0]!=264:raise ValueError('Expected WotLK M2 v264')
    # Some synthetic/legacy test models contain only the short mesh header.
    offsets=[struct.unpack_from('<II',data,h) for h in (28,44,60,80,112,128)]
    if len(data)<304 or any(n and off<304 for n,off in offsets):
        return dict(inspected=False,warnings=['full effect header unavailable'])
    def array(offset,stride):
        n,start=struct.unpack_from('<II',data,offset)
        if start+n*stride>len(data):raise ValueError('Effect declaration outside model')
        return n,start
    sequences,seq=array(28,64);sequence_flags=[struct.unpack_from('<I',data,seq+i*64+12)[0] for i in range(sequences)]
    bones,bone=array(44,88);billboards=sum(bool(struct.unpack_from('<I',data,bone+i*88+4)[0]&0x78) for i in range(bones))
    transforms,_=array(96,60);tracks,off=array(88,20);zero=variable=external=0
    for i in range(tracks):
        track=off+i*20;global_seq=struct.unpack_from('<h',data,track+2)[0]
        count,keys=array(track+12,8);values=[];unknown=False
        for j in range(count):
            n,start=struct.unpack_from('<II',data,keys+j*8)
            if not n:continue
            if global_seq<0 and j<len(sequence_flags) and not sequence_flags[j]&0x60 or start+n*2>len(data):
                unknown=True;continue
            values.extend(struct.unpack_from('<'+'h'*n,data,start))
        zero+=bool(values) and not any(values) and not unknown
        variable+=len(set(values))>1;external+=unknown
    particles=struct.unpack_from('<I',data,296)[0];ribbons=struct.unpack_from('<I',data,288)[0]
    warnings=[]
    for n,label in [(particles,'particle emitters are not rendered'),(ribbons,'ribbons are not rendered'),
                    (billboards,'camera-facing bones are not aligned'),(transforms,'UV animation is not evaluated'),
                    (zero,'zero-opacity geometry is not hidden'),(variable,'material opacity animation is not evaluated'),
                    (external,'external opacity keys require inspection')]:
        if n:warnings.append(f'{label}: {n}')
    return dict(inspected=True,particles=particles,ribbons=ribbons,billboards=billboards,uv_transforms=transforms,
                zero_opacity_tracks=zero,variable_opacity_tracks=variable,external_opacity_tracks=external,warnings=warnings)
