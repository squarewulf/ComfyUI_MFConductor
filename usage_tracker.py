"""
Usage Tracker for MF Conductor
Scans workflows to track which nodes and packages are actually used.
"""

import json
import re
import struct
import zlib
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple
import threading


class UsageTracker:
    """Tracks custom node and package usage by analyzing workflows"""
    
    def __init__(self, comfy_root: Path):
        self.comfy_root = Path(comfy_root)
        self.custom_nodes_path = self.comfy_root / 'custom_nodes'
        self.data_file = Path(__file__).parent / 'user_data' / 'usage_stats.json'
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        
        self._lock = threading.Lock()
        self._node_to_package: Dict[str, str] = {}
        self._usage_data: Dict = self._load_data()
        self._scanning = False
        self._scan_progress = {'current': 0, 'total': 0, 'status': 'idle'}
    
    def _load_data(self) -> Dict:
        """Load existing usage data"""
        if self.data_file.exists():
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            'node_usage': {},      # node_type -> {'count': N, 'last_used': timestamp, 'first_seen': timestamp}
            'package_usage': {},   # package_name -> {'count': N, 'last_used': timestamp, 'nodes_used': [...]}
            'scanned_files': {},   # file_path -> {'hash': str, 'scanned_at': timestamp}
            'last_full_scan': None,
            'total_workflows_scanned': 0
        }
    
    def _save_data(self):
        """Save usage data to disk"""
        with self._lock:
            try:
                with open(self.data_file, 'w', encoding='utf-8') as f:
                    json.dump(self._usage_data, f, indent=2)
            except Exception as e:
                print(f"[Usage Tracker] Failed to save data: {e}")
    
    def build_node_package_map(self, installed_nodes: List[Dict]) -> Dict[str, str]:
        """Build mapping from node class types to package names"""
        node_to_pkg = {}
        
        for node_info in installed_nodes:
            package_name = node_info.get('folder_name', node_info.get('name', 'Unknown'))
            node_types = node_info.get('provided_nodes') or node_info.get('node_types') or []
            
            for node_type in node_types:
                node_to_pkg[node_type] = package_name
        
        self._node_to_package = node_to_pkg
        return node_to_pkg
    
    def get_scan_progress(self) -> Dict:
        """Get current scan progress"""
        return self._scan_progress.copy()
    
    def is_scanning(self) -> bool:
        """Check if a scan is in progress"""
        return self._scanning
    
    def scan_workflows(self, folders: List[str] = None, force_rescan: bool = False) -> Dict:
        """
        Scan workflow files in specified folders.
        
        Args:
            folders: List of folder names to scan (e.g., ['output', 'input'])
                     Defaults to ['output', 'input', 'user']
            force_rescan: If True, rescan all files even if already scanned
        
        Returns:
            Scan results summary
        """
        if self._scanning:
            return {'success': False, 'message': 'Scan already in progress'}
        
        self._scanning = True
        self._scan_progress = {'current': 0, 'total': 0, 'status': 'starting'}
        
        try:
            if folders is None:
                folders = ['output', 'input', 'user']
            
            # Collect all files to scan
            files_to_scan = []
            for folder_name in folders:
                folder_path = self.comfy_root / folder_name
                if folder_path.exists():
                    # PNG and WebP files (may contain workflow metadata)
                    files_to_scan.extend(folder_path.rglob('*.png'))
                    files_to_scan.extend(folder_path.rglob('*.webp'))
                    # JSON workflow files
                    files_to_scan.extend(folder_path.rglob('*.json'))
            
            self._scan_progress['total'] = len(files_to_scan)
            self._scan_progress['status'] = 'scanning'
            
            new_workflows = 0
            nodes_found = set()
            
            for i, file_path in enumerate(files_to_scan):
                self._scan_progress['current'] = i + 1
                
                # Skip if already scanned (unless force_rescan)
                file_key = str(file_path.relative_to(self.comfy_root))
                file_mtime = file_path.stat().st_mtime
                
                if not force_rescan:
                    cached = self._usage_data['scanned_files'].get(file_key)
                    if cached and cached.get('mtime') == file_mtime:
                        continue
                
                # Extract workflow from file
                workflow = self._extract_workflow(file_path)
                if workflow:
                    nodes = self._extract_nodes_from_workflow(workflow)
                    if nodes:
                        new_workflows += 1
                        nodes_found.update(nodes)
                        self._record_usage(nodes, file_path)
                
                # Mark as scanned
                self._usage_data['scanned_files'][file_key] = {
                    'mtime': file_mtime,
                    'scanned_at': datetime.now().isoformat()
                }
            
            self._usage_data['last_full_scan'] = datetime.now().isoformat()
            self._usage_data['total_workflows_scanned'] += new_workflows
            self._save_data()
            
            self._scan_progress['status'] = 'complete'
            
            return {
                'success': True,
                'files_scanned': len(files_to_scan),
                'new_workflows': new_workflows,
                'unique_nodes_found': len(nodes_found)
            }
            
        except Exception as e:
            self._scan_progress['status'] = 'error'
            return {'success': False, 'message': str(e)}
        finally:
            self._scanning = False
    
    def _extract_workflow(self, file_path: Path) -> Optional[Dict]:
        """Extract workflow data from a file"""
        try:
            suffix = file_path.suffix.lower()
            
            if suffix == '.json':
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Could be a workflow or API format
                    if isinstance(data, dict):
                        return data
                        
            elif suffix == '.png':
                return self._extract_png_workflow(file_path)
                
            elif suffix == '.webp':
                return self._extract_webp_workflow(file_path)
                
        except Exception:
            pass
        return None
    
    def _extract_png_workflow(self, file_path: Path) -> Optional[Dict]:
        """Extract workflow from PNG tEXt chunks"""
        try:
            with open(file_path, 'rb') as f:
                # Verify PNG signature
                signature = f.read(8)
                if signature != b'\x89PNG\r\n\x1a\n':
                    return None
                
                while True:
                    chunk_header = f.read(8)
                    if len(chunk_header) < 8:
                        break
                    
                    length = struct.unpack('>I', chunk_header[:4])[0]
                    chunk_type = chunk_header[4:8]
                    
                    if chunk_type == b'tEXt':
                        data = f.read(length)
                        f.read(4)  # CRC
                        
                        null_idx = data.find(b'\x00')
                        if null_idx > 0:
                            keyword = data[:null_idx].decode('latin-1')
                            value = data[null_idx + 1:].decode('utf-8', errors='ignore')
                            
                            if keyword in ('workflow', 'prompt'):
                                try:
                                    return json.loads(value)
                                except json.JSONDecodeError:
                                    pass
                    
                    elif chunk_type == b'iTXt':
                        data = f.read(length)
                        f.read(4)  # CRC
                        
                        null_idx = data.find(b'\x00')
                        if null_idx > 0:
                            keyword = data[:null_idx].decode('latin-1')
                            if keyword in ('workflow', 'prompt'):
                                # Skip compression flag, method, language, translated keyword
                                rest = data[null_idx + 1:]
                                # Find the text after null terminators
                                parts = rest.split(b'\x00', 3)
                                if len(parts) >= 3:
                                    text = parts[-1].decode('utf-8', errors='ignore')
                                    try:
                                        return json.loads(text)
                                    except json.JSONDecodeError:
                                        pass
                    
                    elif chunk_type == b'IEND':
                        break
                    else:
                        f.seek(length + 4, 1)  # Skip data and CRC
                        
        except Exception:
            pass
        return None
    
    def _extract_webp_workflow(self, file_path: Path) -> Optional[Dict]:
        """Extract workflow from WebP EXIF data"""
        try:
            with open(file_path, 'rb') as f:
                data = f.read()
                
            # Look for JSON-like content in the file
            # ComfyUI stores workflow in EXIF UserComment
            workflow_match = re.search(rb'"workflow"\s*:\s*\{', data)
            if workflow_match:
                start = workflow_match.start()
                # Try to find the JSON object
                brace_count = 0
                json_start = None
                for i in range(start, len(data)):
                    if data[i:i+1] == b'{':
                        if json_start is None:
                            json_start = i
                        brace_count += 1
                    elif data[i:i+1] == b'}':
                        brace_count -= 1
                        if brace_count == 0 and json_start is not None:
                            try:
                                json_str = data[json_start:i+1].decode('utf-8', errors='ignore')
                                return json.loads(json_str)
                            except json.JSONDecodeError:
                                pass
                            break
        except Exception:
            pass
        return None
    
    def _extract_nodes_from_workflow(self, workflow: Dict) -> Set[str]:
        """Extract node class types from a workflow"""
        nodes = set()
        
        # Handle different workflow formats
        if isinstance(workflow, dict):
            # API format: {"1": {"class_type": "KSampler", ...}, ...}
            for key, value in workflow.items():
                if isinstance(value, dict):
                    class_type = value.get('class_type')
                    if class_type:
                        nodes.add(class_type)
                    
                    # Also check nested 'nodes' array (graph format)
                    if key == 'nodes' and isinstance(value, list):
                        for node in value:
                            if isinstance(node, dict):
                                node_type = node.get('type')
                                if node_type:
                                    nodes.add(node_type)
            
            # Graph format: {"nodes": [...], "links": [...]}
            if 'nodes' in workflow and isinstance(workflow['nodes'], list):
                for node in workflow['nodes']:
                    if isinstance(node, dict):
                        node_type = node.get('type')
                        if node_type:
                            nodes.add(node_type)
        
        return nodes
    
    def _record_usage(self, nodes: Set[str], source_file: Path):
        """Record usage of nodes"""
        now = datetime.now().isoformat()
        
        with self._lock:
            # Record node usage
            for node_type in nodes:
                if node_type not in self._usage_data['node_usage']:
                    self._usage_data['node_usage'][node_type] = {
                        'count': 0,
                        'first_seen': now,
                        'last_used': now
                    }
                
                self._usage_data['node_usage'][node_type]['count'] += 1
                self._usage_data['node_usage'][node_type]['last_used'] = now
            
            # Record package usage (if we have the mapping)
            packages_used = defaultdict(set)
            for node_type in nodes:
                pkg = self._node_to_package.get(node_type)
                if pkg:
                    packages_used[pkg].add(node_type)
            
            for pkg_name, pkg_nodes in packages_used.items():
                if pkg_name not in self._usage_data['package_usage']:
                    self._usage_data['package_usage'][pkg_name] = {
                        'count': 0,
                        'first_seen': now,
                        'last_used': now,
                        'nodes_used': []
                    }
                
                self._usage_data['package_usage'][pkg_name]['count'] += 1
                self._usage_data['package_usage'][pkg_name]['last_used'] = now
                
                # Track which nodes from this package were used
                existing_nodes = set(self._usage_data['package_usage'][pkg_name]['nodes_used'])
                existing_nodes.update(pkg_nodes)
                self._usage_data['package_usage'][pkg_name]['nodes_used'] = list(existing_nodes)
    
    def get_usage_stats(self) -> Dict:
        """Get comprehensive usage statistics"""
        stats = {
            'last_scan': self._usage_data.get('last_full_scan'),
            'total_workflows': self._usage_data.get('total_workflows_scanned', 0),
            'total_files_tracked': len(self._usage_data.get('scanned_files', {})),
            'node_stats': [],
            'package_stats': [],
            'unused_packages': [],
            'recommendations': []
        }
        
        # Get all installed packages for comparison
        installed_packages = set()
        try:
            for item in self.custom_nodes_path.iterdir():
                if item.is_dir() and not item.name.startswith('.') and not item.name.endswith('.disabled'):
                    installed_packages.add(item.name)
        except Exception:
            pass
        
        # Package usage stats
        package_usage = self._usage_data.get('package_usage', {})
        used_packages = set(package_usage.keys())
        
        for pkg_name in installed_packages:
            pkg_data = package_usage.get(pkg_name, {})
            stats['package_stats'].append({
                'name': pkg_name,
                'count': pkg_data.get('count', 0),
                'last_used': pkg_data.get('last_used'),
                'first_seen': pkg_data.get('first_seen'),
                'nodes_used': len(pkg_data.get('nodes_used', [])),
                'is_used': pkg_name in used_packages
            })
        
        # Sort by usage count
        stats['package_stats'].sort(key=lambda x: x['count'], reverse=True)
        
        # Find unused packages
        stats['unused_packages'] = [
            pkg for pkg in installed_packages 
            if pkg not in used_packages
        ]
        
        # Node usage stats (top 50)
        node_usage = self._usage_data.get('node_usage', {})
        for node_type, data in sorted(node_usage.items(), key=lambda x: x[1]['count'], reverse=True)[:50]:
            stats['node_stats'].append({
                'type': node_type,
                'package': self._node_to_package.get(node_type, 'Unknown'),
                'count': data['count'],
                'last_used': data['last_used']
            })
        
        # Generate recommendations
        stats['recommendations'] = self._generate_recommendations(stats)
        
        return stats
    
    def _generate_recommendations(self, stats: Dict) -> List[Dict]:
        """Generate recommendations based on usage data"""
        recommendations = []
        
        # Packages never used
        if stats['unused_packages']:
            recommendations.append({
                'type': 'unused',
                'severity': 'info',
                'title': f"{len(stats['unused_packages'])} packages never used",
                'description': 'These packages have no recorded usage. Consider disabling them for faster startup.',
                'packages': stats['unused_packages'][:10]  # Show first 10
            })
        
        # Packages not used recently (30+ days)
        now = datetime.now()
        stale_packages = []
        for pkg in stats['package_stats']:
            if pkg['last_used']:
                try:
                    last_used = datetime.fromisoformat(pkg['last_used'])
                    if (now - last_used).days > 30:
                        stale_packages.append(pkg['name'])
                except Exception:
                    pass
        
        if stale_packages:
            recommendations.append({
                'type': 'stale',
                'severity': 'info',
                'title': f"{len(stale_packages)} packages unused for 30+ days",
                'description': 'These packages haven\'t been used recently.',
                'packages': stale_packages[:10]
            })
        
        # Low usage packages (used only 1-2 times)
        low_usage = [
            pkg['name'] for pkg in stats['package_stats']
            if 0 < pkg['count'] <= 2
        ]
        if low_usage:
            recommendations.append({
                'type': 'low_usage',
                'severity': 'info',
                'title': f"{len(low_usage)} packages rarely used",
                'description': 'These packages have been used only 1-2 times.',
                'packages': low_usage[:10]
            })
        
        return recommendations
    
    def clear_data(self):
        """Clear all usage data"""
        with self._lock:
            self._usage_data = {
                'node_usage': {},
                'package_usage': {},
                'scanned_files': {},
                'last_full_scan': None,
                'total_workflows_scanned': 0
            }
            self._save_data()
    
    def record_execution(self, nodes: List[str]):
        """
        Record nodes from a live execution.
        Can be called by execution hooks.
        """
        if nodes:
            self._record_usage(set(nodes), Path('live_execution'))
            self._save_data()


# Global instance
_tracker: Optional[UsageTracker] = None


def get_usage_tracker(comfy_root: Path = None) -> UsageTracker:
    """Get or create the global usage tracker instance"""
    global _tracker
    if _tracker is None:
        if comfy_root is None:
            comfy_root = Path(__file__).parent.parent.parent
        _tracker = UsageTracker(comfy_root)
    return _tracker
