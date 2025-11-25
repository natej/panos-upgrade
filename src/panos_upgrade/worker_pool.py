"""Thread pool manager for concurrent upgrade processing."""

import queue
import threading
import time
from typing import Callable, Optional, Any
from dataclasses import dataclass

from panos_upgrade.logging_config import get_logger
from panos_upgrade.models import WorkerStatus


@dataclass
class WorkItem:
    """Work item for the queue."""
    job_id: str
    device_serial: str
    work_func: Callable
    args: tuple = ()
    kwargs: dict = None
    
    def __post_init__(self):
        if self.kwargs is None:
            self.kwargs = {}


class WorkerThread(threading.Thread):
    """Worker thread that processes jobs from the queue."""
    
    def __init__(self, worker_id: int, work_queue: queue.Queue, 
                 status_callback: Optional[Callable] = None):
        """
        Initialize worker thread.
        
        Args:
            worker_id: Unique worker identifier
            work_queue: Queue to pull work items from
            status_callback: Callback function to report status changes
        """
        super().__init__(daemon=True, name=f"Worker-{worker_id}")
        self.worker_id = worker_id
        self.work_queue = work_queue
        self.status_callback = status_callback
        self.logger = get_logger(f"panos_upgrade.worker.{worker_id}")
        self._stop_event = threading.Event()
        self._current_job: Optional[WorkItem] = None
        self._status = WorkerStatus(
            worker_id=worker_id,
            status="idle"
        )
    
    def run(self):
        """Main worker loop."""
        self.logger.info(f"Worker {self.worker_id} started")
        self._update_status("idle")
        
        while not self._stop_event.is_set():
            try:
                # Get work item with timeout to allow checking stop event
                try:
                    work_item = self.work_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                if work_item is None:  # Poison pill
                    break
                
                self._current_job = work_item
                self._update_status("busy", work_item.job_id, work_item.device_serial)
                
                self.logger.info(
                    f"Worker {self.worker_id} processing job {work_item.job_id} "
                    f"for device {work_item.device_serial}"
                )
                
                try:
                    # Execute the work function
                    work_item.work_func(*work_item.args, **work_item.kwargs)
                except Exception as e:
                    self.logger.error(
                        f"Worker {self.worker_id} error processing job {work_item.job_id}: {e}",
                        exc_info=True
                    )
                    self._update_status("error")
                finally:
                    self.work_queue.task_done()
                    self._current_job = None
                    self._update_status("idle")
            
            except Exception as e:
                self.logger.error(f"Worker {self.worker_id} unexpected error: {e}", exc_info=True)
                self._update_status("error")
        
        self.logger.info(f"Worker {self.worker_id} stopped")
    
    def stop(self):
        """Stop the worker thread."""
        self._stop_event.set()
    
    def _update_status(self, status: str, job_id: str = "", device: str = ""):
        """Update worker status."""
        self._status.status = status
        self._status.current_job_id = job_id
        self._status.current_device = device
        
        if self.status_callback:
            try:
                self.status_callback(self._status)
            except Exception as e:
                self.logger.error(f"Error in status callback: {e}")
    
    @property
    def status(self) -> WorkerStatus:
        """Get current worker status."""
        return self._status


class WorkerPool:
    """Manages a pool of worker threads for concurrent processing."""
    
    def __init__(self, num_workers: int, max_queue_size: int = 1000):
        """
        Initialize worker pool.
        
        Args:
            num_workers: Number of worker threads
            max_queue_size: Maximum queue size
        """
        self.num_workers = num_workers
        self.work_queue: queue.Queue = queue.Queue(maxsize=max_queue_size)
        self.workers: list[WorkerThread] = []
        self.logger = get_logger("panos_upgrade.worker_pool")
        self._lock = threading.Lock()
        self._running = False
    
    def start(self, status_callback: Optional[Callable] = None):
        """
        Start all worker threads.
        
        Args:
            status_callback: Callback function for worker status updates
        """
        with self._lock:
            if self._running:
                self.logger.warning("Worker pool already running")
                return
            
            self.logger.info(f"Starting worker pool with {self.num_workers} workers")
            
            for i in range(self.num_workers):
                worker = WorkerThread(i, self.work_queue, status_callback)
                worker.start()
                self.workers.append(worker)
            
            self._running = True
            self.logger.info("Worker pool started")
    
    def stop(self, timeout: float = 30.0):
        """
        Stop all worker threads.
        
        Args:
            timeout: Maximum time to wait for workers to finish
        """
        with self._lock:
            if not self._running:
                self.logger.warning("Worker pool not running")
                return
            
            self.logger.info("Stopping worker pool")
            
            # Signal all workers to stop
            for worker in self.workers:
                worker.stop()
            
            # Add poison pills to wake up any waiting workers
            for _ in range(len(self.workers)):
                try:
                    self.work_queue.put(None, block=False)
                except queue.Full:
                    pass
            
            # Wait for workers to finish
            for worker in self.workers:
                worker.join(timeout=timeout / len(self.workers))
                if worker.is_alive():
                    self.logger.warning(f"Worker {worker.worker_id} did not stop gracefully")
            
            self.workers.clear()
            self._running = False
            self.logger.info("Worker pool stopped")
    
    def submit(self, job_id: str, device_serial: str, work_func: Callable, 
               *args, **kwargs) -> bool:
        """
        Submit work to the pool.
        
        Args:
            job_id: Job identifier
            device_serial: Device serial number
            work_func: Function to execute
            *args: Positional arguments for work_func
            **kwargs: Keyword arguments for work_func
            
        Returns:
            True if work was queued, False if queue is full
        """
        if not self._running:
            self.logger.error("Cannot submit work: worker pool not running")
            return False
        
        work_item = WorkItem(
            job_id=job_id,
            device_serial=device_serial,
            work_func=work_func,
            args=args,
            kwargs=kwargs
        )
        
        try:
            self.work_queue.put(work_item, block=False)
            self.logger.debug(f"Submitted job {job_id} for device {device_serial}")
            return True
        except queue.Full:
            self.logger.error(f"Work queue full, cannot submit job {job_id}")
            return False
    
    def get_queue_size(self) -> int:
        """Get current queue size."""
        return self.work_queue.qsize()
    
    def get_worker_statuses(self) -> list[WorkerStatus]:
        """Get status of all workers."""
        return [worker.status for worker in self.workers]
    
    @property
    def is_running(self) -> bool:
        """Check if worker pool is running."""
        return self._running

