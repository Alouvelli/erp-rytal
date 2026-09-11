import { useEffect, useState } from 'react';
import { gradeApi, classApi, subjectApi } from '../services/api';
import { Evaluation, Class, Subject } from '../types';
import { useAuth } from '../context/AuthContext';
import { PlusIcon, PaperAirplaneIcon } from '@heroicons/react/24/outline';
import { useForm } from 'react-hook-form';
import toast from 'react-hot-toast';

const TYPE_LABELS: Record<string, string> = { CC: 'Contrôle Continu', TP: 'TP', EXAM: 'Examen', RATTRAPAGE: 'Rattrapage', DEVOIR: 'Devoir' };

export default function GradesPage() {
  const { user } = useAuth();
  const [evaluations, setEvaluations] = useState<Evaluation[]>([]);
  const [classes, setClasses] = useState<Class[]>([]);
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [selected, setSelected] = useState<Evaluation | null>(null);
  const [gradeInputs, setGradeInputs] = useState<Record<string, string>>({});
  const { register, handleSubmit, reset } = useForm();

  const canEdit = user?.role !== 'STUDENT';
  const isStudent = user?.role === 'STUDENT';

  const load = () => gradeApi.getEvaluations().then(({ data }) => setEvaluations(data.data));

  useEffect(() => {
    load();
    classApi.getAll().then(({ data }) => setClasses(data.data));
    subjectApi.getAll().then(({ data }) => setSubjects(data.data));
  }, []);

  const createEval = async (data: any) => {
    try {
      await gradeApi.createEvaluation({ ...data, semester: Number(data.semester), maxScore: Number(data.maxScore), weight: Number(data.weight) });
      toast.success('Évaluation créée');
      setShowModal(false); reset(); load();
    } catch (e: any) { toast.error(e.response?.data?.message || 'Erreur'); }
  };

  const saveGrades = async () => {
    if (!selected) return;
    const grades = (selected.grades || []).map(g => ({
      studentId: g.studentId,
      score: gradeInputs[g.studentId] !== undefined ? parseFloat(gradeInputs[g.studentId]) : g.score,
    }));
    try {
      await gradeApi.saveGrades({ evaluationId: selected.id, grades });
      toast.success('Notes enregistrées');
    } catch { toast.error('Erreur'); }
  };

  const publish = async (evalId: string) => {
    await gradeApi.publish(evalId);
    toast.success('Notes publiées et étudiants notifiés');
    load();
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Notes</h1>
          <p className="text-sm text-gray-500 mt-1">Gestion des évaluations et notes</p>
        </div>
        {canEdit && (
          <button onClick={() => setShowModal(true)} className="btn-primary">
            <PlusIcon className="w-4 h-4" /> Nouvelle évaluation
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Evaluations list */}
        <div className="space-y-3">
          <h2 className="font-semibold text-gray-700 dark:text-gray-300">Évaluations</h2>
          {evaluations.length === 0 && <p className="text-gray-400 text-sm">Aucune évaluation</p>}
          {evaluations.map(e => (
            <div key={e.id}
              onClick={() => setSelected(e)}
              className={`card p-4 cursor-pointer transition-all hover:shadow-md ${selected?.id === e.id ? 'ring-2 ring-primary-500' : ''}`}>
              <div className="flex items-start justify-between">
                <div>
                  <p className="font-medium text-gray-900 dark:text-white">{e.name}</p>
                  <p className="text-sm text-gray-500 mt-0.5">{e.subject.name} • {new Date(e.date).toLocaleDateString('fr-FR')}</p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="badge badge-blue">{TYPE_LABELS[e.type]}</span>
                  <span className="badge badge-gray">/{e.maxScore}</span>
                </div>
              </div>
              {canEdit && (
                <button onClick={(ev) => { ev.stopPropagation(); publish(e.id); }}
                  className="mt-2 flex items-center gap-1 text-xs text-primary-600 hover:underline">
                  <PaperAirplaneIcon className="w-3 h-3" /> Publier les notes
                </button>
              )}
            </div>
          ))}
        </div>

        {/* Grade entry / view */}
        {selected && (
          <div className="card p-4">
            <h2 className="font-semibold text-gray-900 dark:text-white mb-3">
              Notes — {selected.name}
            </h2>
            {(selected.grades || []).length === 0 ? (
              <p className="text-gray-400 text-sm">Aucun étudiant inscrit</p>
            ) : (
              <div className="space-y-2">
                {(selected.grades || []).map(g => (
                  <div key={g.id} className="flex items-center justify-between gap-3 p-2 bg-gray-50 dark:bg-gray-800 rounded-lg">
                    <span className="text-sm">{g.student.user.firstName} {g.student.user.lastName}</span>
                    {canEdit ? (
                      <input type="number" min={0} max={selected.maxScore} step={0.5}
                        defaultValue={g.score ?? ''}
                        onChange={e => setGradeInputs(prev => ({ ...prev, [g.studentId]: e.target.value }))}
                        className="input w-20 text-center py-1"
                        placeholder="-" />
                    ) : (
                      <span className={`font-bold text-sm ${g.score !== null && g.score !== undefined && g.score >= 10 ? 'text-green-600' : 'text-red-500'}`}>
                        {g.score !== null && g.score !== undefined ? `${g.score}/${selected.maxScore}` : 'NR'}
                      </span>
                    )}
                  </div>
                ))}
                {canEdit && (
                  <button onClick={saveGrades} className="btn-primary w-full justify-center mt-3">
                    Enregistrer les notes
                  </button>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Create evaluation modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="card w-full max-w-md p-6">
            <h2 className="text-lg font-semibold mb-4">Nouvelle évaluation</h2>
            <form onSubmit={handleSubmit(createEval)} className="space-y-3">
              <div>
                <label className="label">Nom</label>
                <input className="input" {...register('name', { required: true })} placeholder="Ex: CC1 - Développement Web" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Classe</label>
                  <select className="input" {...register('classId', { required: true })}>
                    <option value="">Choisir...</option>
                    {classes.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                </div>
                <div>
                  <label className="label">Matière</label>
                  <select className="input" {...register('subjectId', { required: true })}>
                    <option value="">Choisir...</option>
                    {subjects.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                </div>
                <div>
                  <label className="label">Type</label>
                  <select className="input" {...register('type', { required: true })}>
                    {Object.entries(TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </div>
                <div>
                  <label className="label">Date</label>
                  <input type="date" className="input" {...register('date', { required: true })} />
                </div>
                <div>
                  <label className="label">Note max</label>
                  <input type="number" className="input" defaultValue={20} {...register('maxScore', { required: true })} />
                </div>
                <div>
                  <label className="label">Semestre</label>
                  <select className="input" {...register('semester', { required: true })}>
                    <option value={1}>Semestre 1</option>
                    <option value={2}>Semestre 2</option>
                  </select>
                </div>
              </div>
              <div className="flex gap-3 pt-2">
                <button type="submit" className="btn-primary flex-1 justify-center">Créer</button>
                <button type="button" onClick={() => { setShowModal(false); reset(); }} className="btn-secondary flex-1 justify-center">Annuler</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
