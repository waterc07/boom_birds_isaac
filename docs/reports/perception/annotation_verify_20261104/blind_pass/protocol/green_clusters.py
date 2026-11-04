import json, sys
from pathlib import Path
import numpy as np
from PIL import Image

def clusters(path, min_px=2):
    img = np.asarray(Image.open(path).convert("RGB")).astype(np.int16)
    r,g,b = img[...,0], img[...,1], img[...,2]
    mask = (g >= 90) & (g - r >= 25) & (g - b >= 25)
    # 4-connectivity labeling
    h,w = mask.shape
    lab = np.zeros((h,w), dtype=np.int32)
    cur = 0
    out = []
    import collections
    for y in range(h):
        for x in range(w):
            if mask[y,x] and lab[y,x]==0:
                cur += 1
                q = collections.deque([(y,x)]); lab[y,x]=cur
                pts=[]
                while q:
                    cy,cx=q.popleft(); pts.append((cy,cx))
                    for dy,dx in ((1,0),(-1,0),(0,1),(0,-1)):
                        ny,nx=cy+dy,cx+dx
                        if 0<=ny<h and 0<=nx<w and mask[ny,nx] and lab[ny,nx]==0:
                            lab[ny,nx]=cur; q.append((ny,nx))
                if len(pts)>=min_px:
                    ys=[p[0] for p in pts]; xs=[p[1] for p in pts]
                    out.append(dict(size=len(pts), bbox=[min(xs),min(ys),max(xs),max(ys)],
                                    centroid=[round(sum(xs)/len(xs),2), round(sum(ys)/len(ys),2)],
                                    mean=[int(img[ys[i],xs[i],0]) for i in range(0)],
                                    maxgreen=int(g[ys,xs].max())))
    return out

cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
res = {}
for item in cfg:
    res[item["name"]] = clusters(item["path"])
print(json.dumps(res, indent=1))
